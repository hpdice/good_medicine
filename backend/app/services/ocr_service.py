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

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.core.logging import logger

# apt의 tesseract-ocr-kor은 속도 우선의 "fast" 모델이라 정확도가 떨어진다(실측
# 2026-09-16: 용량 "20mg"을 "2000"으로 오인식하는 등). tessdata_best(LSTM 고정밀
# 모델)를 여기 받아두면 그쪽을 쓴다 — 없으면(운영 이미지 등) 기본 fast 모델로
# 조용히 폴백한다. TODO: 데모 이후 Dockerfile에 정식으로 편입할 것(지금은 컨테이너
# 재시작까지만 버티는 /tmp 임시 배치).
_BEST_TESSDATA_DIR = "/tmp/tessdata_best"
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
_NAME_FORM_RE = re.compile(
    rf"[가-힣]{{2,20}}(?:{_DRUG_FORM})(?:\d+(?:\.\d+)?(?:{_UNIT})?)?", re.IGNORECASE
)
# 제형 글자 없이 "이름+용량"만 있는 드문 케이스(예: 병용 캡슐이 아닌 '~산' 등) 폴백
_NAME_UNIT_RE = re.compile(
    rf"[가-힣][가-힣A-Za-z0-9]{{0,19}}\d+(?:\.\d+)?(?:{_UNIT})\b", re.IGNORECASE
)


_CELL_GAP_RE = re.compile(r"\s{2,}")


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
                if 2 <= len(name) <= 50 and name not in out:
                    out.append(name)
                if len(out) >= 20:
                    break
            if len(out) >= 20:
                break
        if len(out) >= 20:
            break
    return out


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
            variants = [img, ImageOps.autocontrast(img.convert("L"), cutoff=2)]

            # 방향/전처리 8가지 조합을 전부 시도하고 "후보가 가장 많이 나온" 시도를
            # 채택한다 — 후보가 1개라도 나오면 바로 멈추던 이전 버전은, 그 1개가
            # "필름코팅정" 같은 일반 설명 문구(진짜 약 이름 아님)인 약한 시도에서
            # 멈춰버리고 훨씬 더 잘 읽힌(한글 인식량이 더 많은) 다른 방향은 아예
            # 안 보는 문제가 실측으로 확인됨(2026-09-16).
            best_text, best_candidates, best_hangul_count = "", [], -1
            for variant_idx, variant in enumerate(variants):
                for angle in (0, 90, 180, 270):
                    rotated = variant.rotate(-angle, expand=True) if angle else variant
                    text = pytesseract.image_to_string(
                        rotated, lang=settings.OCR_TESSERACT_LANG, config=_OCR_CONFIG,
                    )
                    candidates = extract_candidates(text)
                    hangul_count = len(_HANGUL_RE.findall(text))
                    logger.warning(
                        "drugs/ocr variant=%d angle=%d rotated_size=%s text_len=%d "
                        "hangul=%d candidates=%d",
                        variant_idx, angle, rotated.size, len(text), hangul_count,
                        len(candidates),
                    )
                    is_better = (
                        len(candidates) > len(best_candidates)
                        or (len(candidates) == len(best_candidates) and hangul_count > best_hangul_count)
                    )
                    if is_better:
                        best_text, best_candidates, best_hangul_count = text, candidates, hangul_count
                    # 후보 3개 이상이면 충분히 신뢰할 만한 시도로 보고 바로 채택한다
                    # (똑바로 찍은 대부분의 사진은 1번째 시도에서 여기서 끝나 지연 없음).
                    if len(best_candidates) >= 3:
                        return best_text
            return best_text
    except UnidentifiedImageError as e:
        raise UnreadableImageError("이미지 형식을 인식할 수 없습니다.") from e
    except pytesseract.TesseractNotFoundError as e:
        logger.error("tesseract 바이너리를 찾을 수 없음 — 백엔드 이미지 재빌드 필요")
        raise OcrError("서버에 OCR 엔진이 설치되어 있지 않습니다.") from e
    except Exception as e:  # noqa: BLE001 — tesseract 런타임 오류 포괄
        logger.exception("OCR 처리 중 예외")
        raise OcrError("OCR 처리에 실패했습니다.") from e
