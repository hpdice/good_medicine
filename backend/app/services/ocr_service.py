"""처방전·약봉투 이미지 OCR — 서버 측.

이미지는 **메모리에서만** 다룬다. 이 모듈의 어떤 함수도 파일을 쓰지 않으며,
호출부(`api/v1/drugs.py`)도 OCR 직후 바이트를 폐기한다. 이미지의 영구 사본은
사용자 기기(클라이언트)에만 존재한다.

`extract_candidates`는 Flutter `camera_provider._extractCandidates`의 파이썬 이식본이다 —
두 곳의 정규식이 항상 같은 결과를 내도록 함께 유지한다.
"""

import io
import os
import re
from concurrent.futures import ThreadPoolExecutor

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.core.logging import logger

# apt의 tesseract-ocr-kor은 속도 우선의 "fast" 모델이라 정확도가 떨어진다(실측
# 2026-09-16: 용량 "20mg"을 "2000"으로 오인식하는 등). tessdata_best(LSTM 고정밀
# 모델)는 Dockerfile이 이미지에 넣어 둔다 — 없으면(이미지를 안 다시 빌드한 환경 등) 기본 fast
# 모델로 조용히 폴백한다.
_BEST_TESSDATA_DIR = "/usr/share/tessdata_best"
_OCR_CONFIG = (
    f"--tessdata-dir {_BEST_TESSDATA_DIR}" if os.path.isdir(_BEST_TESSDATA_DIR) else ""
)


class OcrError(Exception):
    """OCR 처리 실패 (엔진/런타임 측) — 호출부는 503으로 매핑."""


class UnreadableImageError(OcrError):
    """업로드된 바이트가 이미지가 아니거나 손상됨 — 호출부는 415로 매핑."""


_DRUG_FORM = r"정|캡슐|주사|액|시럽|연고|크림"
_UNIT = r"mg|㎎|mcg|μg|g|ml|mL"
_FORM_END_RE = re.compile(rf"({_DRUG_FORM})$")
_DOSAGE_ONLY_RE = re.compile(rf"^\d+(\.\d+)?({_UNIT})$", re.IGNORECASE)
_HANGUL_RE = re.compile(r"[가-힣]")
# 이름(한글 2~20자) + 제형 + (선택)용량 — 표 라벨에서 옆 칸(가격 등) 텍스트가 완전히
# 안 떨어지고 붙어 나와도, 매칭되는 부분만 정확히 뽑아내고 나머지는 버린다.
# 이름 가운데 숫자도 허용한다 — '아니스펜8시간이알서방정'이 '8'에서 끊겨 '시간이알서방정' 조각만
# 남던 문제(실측 2026-10-19). 맨 앞은 한글이어야 해서 '1회투약량1' 같은 숫자 시작 줄은 안 걸린다.
_NAME_FORM_RE = re.compile(
    rf"[가-힣][가-힣0-9]{{1,19}}(?:{_DRUG_FORM})(?:\d+(?:\.\d+)?(?:{_UNIT})?)?", re.IGNORECASE
)
# 제형 글자 없이 "이름+용량"만 있는 드문 케이스(예: 병용 캡슐이 아닌 '~산' 등) 폴백
_NAME_UNIT_RE = re.compile(
    rf"[가-힣][가-힣A-Za-z0-9]{{0,19}}\d+(?:\.\d+)?(?:{_UNIT})\b", re.IGNORECASE
)


_CELL_GAP_RE = re.compile(r"\s{2,}")
# 제형·서방 같은 "설명어"만 남는 조각(예: 줄이 잘려 '서방정', '알서방정'만 읽힘)은 약 이름이 아니다.
# 그대로 두면 ILIKE 폴백이 '서방정'이 들어간 아무 약(바스티난엠알서방정 등)에 조용히 매칭한다 —
# 실측 2026-10-19. 설명어·숫자·제형을 걷어내고 한글 2자 이상이 안 남으면 버린다.
_GENERIC_WORDS_RE = re.compile(
    rf"서방|필름코팅|장용|구강붕해|연질|경질|이알|시간|\d+(?:\.\d+)?(?:{_UNIT})?|{_DRUG_FORM}",
    re.IGNORECASE,
)


def _is_generic_fragment(name: str) -> bool:
    return len(_HANGUL_RE.findall(_GENERIC_WORDS_RE.sub("", name))) < 2


def extract_candidates(text: str) -> list[str]:
    """OCR 원문 → 약품명 후보 리스트 (최대 20개).

    1) 줄 단위로 자르고 trim
    2) "제형으로 끝나는 줄" + "다음 줄이 순수 용량"이면 두 줄을 합침
    3) 표 형태 라벨(조제 안내문 등)은 Tesseract가 여러 칸(약품명/설명/가격)을 큰
       공백으로 이어붙여 한 줄로 뽑아내므로, 공백 2칸 이상을 칸 구분으로 보고 더 쪼갠다
       (일반 줄글은 큰 공백이 없어 그대로 한 조각).
    4) 각 칸에서 "이름+제형(+용량)" 패턴에 실제로 매칭되는 부분만 정규식으로 뽑는다 —
       칸 전체를 넣지 않아 옆 칸과 덜 떨어진 쓰레기(가격 등)가 안 섞인다.
    """
    lines = [ln.strip() for ln in text.split("\n")]

    merged: list[str] = []
    i = 0
    while i < len(lines):
        if (
            _FORM_END_RE.search(lines[i])
            and i + 1 < len(lines)
            and _DOSAGE_ONLY_RE.match(lines[i + 1])
        ):
            merged.append(lines[i] + lines[i + 1])
            i += 2
        else:
            merged.append(lines[i])
            i += 1

    out: list[str] = []
    for merged_line in merged:
        for cell in _CELL_GAP_RE.split(merged_line):
            cell = cell.strip()
            if not cell or not _HANGUL_RE.search(cell):
                continue
            # 셀 안에서도 이름+제형(+용량) 패턴에 실제로 걸리는 부분만 뽑는다 — 셀
            # 전체를 넣으면 옆 칸과 덜 떨어진 쓰레기(가격 등)가 이름 앞뒤에 남을 수 있음.
            found = _NAME_FORM_RE.findall(cell) or _NAME_UNIT_RE.findall(cell)
            for name in found:
                if 2 <= len(name) <= 50 and name not in out and not _is_generic_fragment(name):
                    out.append(name)
                if len(out) >= 20:
                    break
            if len(out) >= 20:
                break
        if len(out) >= 20:
            break
    # 띠 경계에서 이름 앞이 잘려 읽힌 조각('스펜8시간이알서방정')은 더 긴 후보
    # ('아니스펜8시간이알서방정')에 이미 담겨 있으니 버린다.
    return [c for c in out if not any(o != c and o.endswith(c) for o in out)]


# (띠 개수, 겹침 비율) — 띠 경계에 걸린 줄은 그 구성에선 읽히지 않으므로 경계가 다르게 떨어지는
# 두 구성을 모두 읽어 합친다. 실측(2026-10-19): 한 구성만으로는 약 4개 중 3개만 읽히는 경우가
# 구성마다 달랐고(4/0.1→3, 4/0.3→3, 5/0.3→4, 6/0.25→2), 읽힌 약이 구성마다 서로 달랐다.
_TILE_LAYOUTS = ((4, 0.3), (5, 0.3))


# OCR 입력의 긴 변 상한(px). 폰 사진(4000px)을 그대로 읽으면 띠 9장만 23초(실측 2026-10-19)로
# 앱의 OCR 요청 타임아웃(30초)을 넘긴다. 줄이면 처리량이 면적에 비례해 줄어든다(2400px: 12초).
# 작은 글씨(용량 표기)가 뭉개지지 않는 선에서 3000px로 잡았다.
_MAX_SIDE = 3000
# 띠 읽기(psm 6, 줄 단위)는 면적당 가장 오래 걸리는 단계라 더 줄인다 — 3000px에선 띠 9장이 병렬로도
# 11초였다. 이 사진에서 2400px의 인식률은 같았다.
_TILE_MAX_SIDE = 2400
_TILE_WORKERS = 4


def _fit_max_side(img: Image.Image, max_side: int) -> Image.Image:
    """긴 변이 max_side를 넘을 때만 비율 유지로 줄인다(키우지는 않는다)."""
    scale = max_side / max(img.size)
    if scale >= 1:
        return img
    return img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)

# 병렬 tesseract 프로세스끼리 OpenMP 스레드를 또 나누면 오히려 느려진다.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


def _tiled_text(img: Image.Image) -> str:
    """이미지를 가로 띠로 잘라 띠마다 국소 명암 보정 + 줄 단위 읽기(psm 6)로 OCR한 텍스트.
    `_TILE_LAYOUTS`의 모든 구성을 읽어 이어 붙이고, 띠는 스레드 풀로 병렬 처리한다.

    약봉투를 비스듬히·그림자 지게 찍은 사진은 한 장 통째로 레이아웃 분석(psm 3)을 하면
    알약 사진·그림자 영역에 걸려 아래쪽 행(약)을 통째로 버린다. 실측(2026-10-19): 약 4개짜리
    봉투에서 통째 OCR은 2개만 읽었고, 띠로 자르면 3~4개가 읽혔다(어느 줄이 띠 경계에 걸리느냐에
    따라 달라서 호출부가 구성을 바꿔 두 번 읽는다). 전체 한 장 대비는 그림자 쪽 글자를 못 살리므로
    대비도 띠 단위로 다시 맞춘다."""
    gray = _fit_max_side(img.convert("L"), _TILE_MAX_SIDE)
    width, height = gray.size

    tiles: list[Image.Image] = []
    for tile_count, overlap in _TILE_LAYOUTS:
        for i in range(tile_count):
            top = max(0, int(height * (i / tile_count - overlap / 2)))
            bottom = min(height, int(height * ((i + 1) / tile_count + overlap / 2)))
            tiles.append(ImageOps.autocontrast(gray.crop((0, top, width, bottom)), cutoff=1))

    config = f"{_OCR_CONFIG} --psm 6".strip()

    def _read(tile: Image.Image) -> str:
        return pytesseract.image_to_string(tile, lang=settings.OCR_TESSERACT_LANG, config=config)

    with ThreadPoolExecutor(max_workers=_TILE_WORKERS) as pool:
        return "\n".join(pool.map(_read, tiles))


def run_ocr(image_bytes: bytes) -> str:
    """이미지 바이트 → OCR 텍스트. 파일을 만들지 않는다(전부 메모리).

    휴대폰으로 약봉투를 옆으로(세로 글자가 가로로 눕게) 찍어 올리는 경우가 실측으로
    확인되어, 정방향에서 약품명 후보가 하나도 안 나오면 90도씩 돌려가며 재시도한다.
    대부분(정방향 촬영)은 첫 시도에서 바로 끝나 추가 비용이 없다."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            logger.warning(
                "drugs/ocr 입력: bytes=%d size=%s mode=%s format=%s",
                len(image_bytes), img.size, img.mode, img.format,
            )
            if img.mode not in ("L", "RGB"):
                img = img.convert("RGB")

            # 컬러 배경(하늘색 그라데이션 등)에 저대비 글자가 올라간 처방전/라벨은
            # 기본 이진화로는 배경과 글자를 못 가른다 — 실측(2026-09-16)으로 확인된
            # 흔한 실패 케이스. 1차: 원본 그대로. 2차: 그레이스케일+명암 강제 확장.
            # 폰 사진(4000px)을 그대로 읽으면 통째 읽기 8회 + 띠 읽기가 직렬로 45초 걸려 앱의 OCR 요청
            # 타임아웃(30초)을 넘긴다(실측 2026-10-19). 긴 변을 줄이고 방향 시도는 병렬로 돌린다.
            img = _fit_max_side(img, _MAX_SIDE)
            variants = [img, ImageOps.autocontrast(img.convert("L"), cutoff=2)]

            # 방향/전처리 8가지 조합을 시도하고 "후보가 가장 많이 나온" 시도를
            # 채택한다 — 후보가 1개라도 나오면 바로 멈추던 이전 버전은, 그 1개가
            # "필름코팅정" 같은 일반 설명 문구(진짜 약 이름 아님)인 약한 시도에서
            # 멈춰버리고 훨씬 더 잘 읽힌(한글 인식량이 더 많은) 다른 방향은 아예
            # 안 보는 문제가 실측으로 확인됨(2026-09-16).
            best_text, best_candidates, best_hangul_count = "", [], -1
            # 방향별 (후보 수, 후보 글자 수 합) 최고점 — 아래 띠 OCR을 어느 방향부터 시도할지 정하는
            # 데만 쓴다. 한글 글자 수는 틀린 방향의 쓰레기 인식에도 늘어나 방향 판단 근거가 못 되고,
            # 쓰레기 후보는 짧아서 글자 수 합이 맞는 방향 쪽이 크다.
            angle_scores: dict[int, tuple[int, int]] = {}

            def _attempt(job: tuple[int, Image.Image, int]) -> tuple[int, int, str]:
                variant_idx, variant, angle = job
                rotated = variant.rotate(-angle, expand=True) if angle else variant
                text = pytesseract.image_to_string(
                    rotated, lang=settings.OCR_TESSERACT_LANG, config=_OCR_CONFIG,
                )
                return variant_idx, angle, text

            def _consider(variant_idx: int, angle: int, text: str) -> None:
                nonlocal best_text, best_candidates, best_hangul_count
                candidates = extract_candidates(text)
                hangul_count = len(_HANGUL_RE.findall(text))
                logger.warning(
                    "drugs/ocr variant=%d angle=%d text_len=%d hangul=%d candidates=%d",
                    variant_idx, angle, len(text), hangul_count, len(candidates),
                )
                score = (len(candidates), sum(len(c) for c in candidates))
                angle_scores[angle] = max(angle_scores.get(angle, (0, 0)), score)
                if (
                    len(candidates) > len(best_candidates)
                    or (len(candidates) == len(best_candidates) and hangul_count > best_hangul_count)
                ):
                    best_text, best_candidates, best_hangul_count = text, candidates, hangul_count

            with ThreadPoolExecutor(max_workers=_TILE_WORKERS) as pool:
                for variant_idx, variant in enumerate(variants):
                    # 똑바로 찍은 대부분의 사진은 정방향 한 번에서 끝난다(후보 3개 이상이면 충분히
                    # 신뢰) — 나머지 방향은 그게 안 될 때만 병렬로 시도해 지연을 늘리지 않는다.
                    jobs = [(variant_idx, variant, a) for a in (0, 90, 180, 270)]
                    first, rest = jobs[:1] if variant_idx == 0 else [], jobs[1:] if variant_idx == 0 else jobs
                    for result in map(_attempt, first):
                        _consider(*result)
                    if len(best_candidates) >= 3:
                        return best_text
                    for result in pool.map(_attempt, rest):
                        _consider(*result)
                    if len(best_candidates) >= 3:
                        return best_text

            # 통째 OCR이 약을 3개 못 채웠으면(사진에 그림자·알약 그림이 섞여 일부 행이 통째로
            # 빠진 경우) 띠로 잘라 다시 읽는다. 후보가 나온 방향부터 시도하고, 3개 이상 나오면 멈춘다.
            for angle in sorted(angle_scores, key=lambda a: angle_scores[a], reverse=True):
                if angle_scores[angle][0] == 0:
                    break
                rotated = img.rotate(-angle, expand=True) if angle else img
                text = _tiled_text(rotated)
                candidates = extract_candidates(text)
                logger.warning(
                    "drugs/ocr tiled angle=%d text_len=%d candidates=%d",
                    angle, len(text), len(candidates),
                )
                if len(candidates) > len(best_candidates):
                    best_text, best_candidates = text, candidates
                if len(best_candidates) >= 3:
                    break
            return best_text
    except UnidentifiedImageError as e:
        raise UnreadableImageError("이미지 형식을 인식할 수 없습니다.") from e
    except pytesseract.TesseractNotFoundError as e:
        logger.error("tesseract 바이너리를 찾을 수 없음 — 백엔드 이미지 재빌드 필요")
        raise OcrError("서버에 OCR 엔진이 설치되어 있지 않습니다.") from e
    except Exception as e:  # noqa: BLE001 — tesseract 런타임 오류 포괄
        logger.exception("OCR 처리 중 예외")
        raise OcrError("OCR 처리에 실패했습니다.") from e
