"""run_ocr 의 시도 순서(정방향 → 다른 방향 → 띠 읽기)와 결과 선택을 지킨다. Tesseract 는 가짜로 대체한다.

이미지는 비정방형이라 방향·전처리마다 픽셀이 달라 서로 구분된다. 가짜 OCR 은 입력 이미지의 해시로
"이 방향/전처리본에서는 이 글자가 읽힌다"를 돌려준다.
"""
import hashlib
import io

import pytesseract
import pytest
from PIL import Image, ImageOps

from app.services import ocr_service

NAMES = ["가스핀정5mg", "타이레놀정500mg", "푸루나정10mg", "뉴부틴정"]


def _text(n: int, extra_hangul: int = 0) -> str:
    return "\n".join(NAMES[:n]) + "\n" + "가나다" * extra_hangul


def _make_image() -> bytes:
    img = Image.new("RGB", (600, 400), (240, 240, 240))
    for x in range(0, 600, 7):
        for y in range(0, 400, 11):
            img.putpixel((x, y), (x % 255, y % 255, (x * y) % 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _key(img: Image.Image) -> str:
    return hashlib.md5(img.mode.encode() + str(img.size).encode() + img.tobytes()).hexdigest()


@pytest.fixture
def fake_ocr(monkeypatch):
    """fake_ocr(whole={(전처리, 각도): 글자}, tiled={이미지너비: 글자}) -> (run, calls)."""
    data = _make_image()

    def install(whole=None, tiled=None):
        whole, tiled = whole or {}, tiled or {}
        loaded = Image.open(io.BytesIO(data))
        loaded.load()
        variants = [loaded.copy(), ImageOps.autocontrast(loaded.convert("L"), cutoff=2)]
        by_key = {}
        for vi, variant in enumerate(variants):
            for angle in (0, 90, 180, 270):
                rotated = variant.rotate(-angle, expand=True) if angle else variant
                by_key[_key(rotated)] = whole.get((vi, angle), "")
        calls = []

        def fake(img, lang=None, config=""):
            is_tile = "--psm 6" in (config or "")
            calls.append(is_tile)
            return tiled.get(img.size[0], "") if is_tile else by_key.get(_key(img), "")

        monkeypatch.setattr(pytesseract, "image_to_string", fake)
        return (lambda: ocr_service.run_ocr(data)), calls

    return install


def test_upright_photo_with_enough_names_stops_after_one_read(fake_ocr):
    run, calls = fake_ocr(whole={(0, 0): _text(4)})
    assert run() == _text(4)
    assert calls == [False]  # 다른 방향·띠 읽기는 하지 않는다


def test_rotated_photo_is_found_by_trying_other_angles(fake_ocr):
    run, calls = fake_ocr(whole={(0, 90): _text(3)})
    assert run() == _text(3)
    assert len(calls) == 4 and not any(calls)  # 정방향 1 + 나머지 3방향, 띠 읽기 없음


def test_preprocessed_copy_is_tried_when_original_fails(fake_ocr):
    run, _ = fake_ocr(whole={(1, 180): _text(4)})
    assert run() == _text(4)


def test_unreadable_photo_returns_empty_without_tiling(fake_ocr):
    run, calls = fake_ocr()
    assert run() == ""
    assert len(calls) == 8 and not any(calls)  # 전처리 2 × 방향 4, 후보가 한 번도 안 나와 띠 읽기도 건너뜀


def test_tiled_read_is_used_when_whole_read_finds_too_few(fake_ocr):
    run, calls = fake_ocr(whole={(0, 0): _text(1)}, tiled={600: _text(3)})
    assert ocr_service.extract_candidates(run()) == NAMES[:3]  # 띠 읽기 결과(띠마다 읽은 글자를 이어 붙인 것)가 채택됐다
    assert any(calls)  # 띠로 잘라 다시 읽었다


def test_tie_on_candidate_count_prefers_more_hangul(fake_ocr):
    run, _ = fake_ocr(whole={(0, 0): _text(2), (0, 180): _text(2, extra_hangul=5), (1, 0): _text(2, extra_hangul=2)})
    assert run() == _text(2, extra_hangul=5)
