"""처방전·약봉투 이미지 OCR — 서버 측.

이미지는 **메모리에서만** 다룬다. 이 모듈의 어떤 함수도 파일을 쓰지 않으며,
호출부(`api/v1/drugs.py`)도 OCR 직후 바이트를 폐기한다. 이미지의 영구 사본은
사용자 기기(클라이언트)에만 존재한다.

`extract_candidates`는 Flutter `camera_provider._extractCandidates`의 파이썬 이식본이다 —
두 곳의 정규식이 항상 같은 결과를 내도록 함께 유지한다.
"""

import io
import re

import pytesseract
from PIL import Image, UnidentifiedImageError

from app.config import settings
from app.core.logging import logger


class OcrError(Exception):
    """OCR 처리 실패 (엔진/런타임 측) — 호출부는 503으로 매핑."""


class UnreadableImageError(OcrError):
    """업로드된 바이트가 이미지가 아니거나 손상됨 — 호출부는 415로 매핑."""


_DRUG_FORM = r"정|캡슐|주사|액|시럽|연고|크림"
_FORM_END_RE = re.compile(rf"({_DRUG_FORM})$")
_DOSAGE_ONLY_RE = re.compile(r"^\d+(\.\d+)?(mg|㎎|mcg|μg|g|ml|mL)$", re.IGNORECASE)
_DRUG_PATTERN_RE = re.compile(
    rf"({_DRUG_FORM})\d|\d+(mg|㎎|mcg|μg|g|ml|mL)\b|({_DRUG_FORM})$",
    re.IGNORECASE,
)
_HANGUL_RE = re.compile(r"[가-힣]")


def extract_candidates(text: str) -> list[str]:
    """OCR 원문 → 약품명 후보 리스트 (최대 20개).

    1) 줄 단위로 자르고 trim
    2) "제형으로 끝나는 줄" + "다음 줄이 순수 용량"이면 두 줄을 합침
    3) 한글 포함 + (제형+숫자 | 숫자+단위 | 제형으로 끝) + 길이 2~50 인 줄만 남김
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
    for ln in merged:
        if 2 <= len(ln) <= 50 and _HANGUL_RE.search(ln) and _DRUG_PATTERN_RE.search(ln):
            out.append(ln)
        if len(out) >= 20:
            break
    return out


def run_ocr(image_bytes: bytes) -> str:
    """이미지 바이트 → OCR 텍스트. 파일을 만들지 않는다(전부 메모리)."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img.load()
            if img.mode not in ("L", "RGB"):
                img = img.convert("RGB")
            return pytesseract.image_to_string(img, lang=settings.OCR_TESSERACT_LANG)
    except UnidentifiedImageError as e:
        raise UnreadableImageError("이미지 형식을 인식할 수 없습니다.") from e
    except pytesseract.TesseractNotFoundError as e:
        logger.error("tesseract 바이너리를 찾을 수 없음 — 백엔드 이미지 재빌드 필요")
        raise OcrError("서버에 OCR 엔진이 설치되어 있지 않습니다.") from e
    except Exception as e:  # noqa: BLE001 — tesseract 런타임 오류 포괄
        logger.exception("OCR 처리 중 예외")
        raise OcrError("OCR 처리에 실패했습니다.") from e
