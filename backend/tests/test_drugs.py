import app.api.v1.drugs as drugs_api
from app.services.ocr_service import OcrError, extract_candidates
from tests.factories import make_drug, register_and_login


async def test_search_finds_drug_by_partial_name(client, session_factory):
    async with session_factory() as session:
        await make_drug(session, "아스피린정100밀리그램")

    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.get("/drugs", params={"q": "아스피린"}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert len(body) >= 1
    assert any("아스피린" in d["item_name"] for d in body)


async def test_search_without_token_rejected(client):
    res = await client.get("/drugs", params={"q": "아스피린"})
    assert res.status_code in (401, 403)


async def test_get_drug_by_id(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "타이레놀정500밀리그램")

    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.get(f"/drugs/{drug.id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == str(drug.id)


async def test_get_drug_by_id_not_found(client):
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    fake_id = "00000000-0000-0000-0000-000000000000"
    res = await client.get(f"/drugs/{fake_id}", headers=headers)
    assert res.status_code == 404


async def test_match_names_finds_ingredient_name_when_brand_hides_it_in_parens(
    client, session_factory
):
    """실제 와파린 사례: 브랜드명이 성분명을 괄호 안에 숨기면('쿠파린정(와파린나트륨)')
    drug_key/전체문자열 ILIKE가 '와파린정'(성분명+제형) 입력에 실패한다.
    성분명 폴백 매칭(4순위)이 이를 잡아내야 한다."""
    async with session_factory() as session:
        drug = await make_drug(
            session,
            "쿠파린정2밀리그램(와파린나트륨)",
            ingr_name=[{"kor": "와파린나트륨", "eng": "", "amount": "", "dur_code": "M000001"}],
        )

    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.post(
        "/drugs/match-names", json={"names": ["와파린정"]}, headers=headers
    )
    assert res.status_code == 200
    result = res.json()[0]
    assert result["matched"] is not None
    assert result["matched"]["id"] == str(drug.id)


async def test_match_names_prefers_precise_match_over_ingredient_fallback(
    client, session_factory
):
    """정확한 전체 문자열 매칭(3순위)이 존재하면, 더 넓은 범위의 성분명 폴백(4순위)이
    이를 밀어내면 안 된다 — 조합제(콤보약)가 단일 성분 정밀 매칭보다 먼저 뜨는
    회귀를 방지."""
    async with session_factory() as session:
        precise = await make_drug(session, "유한메토트렉세이트정")
        await make_drug(
            session,
            "네오메토주(메토트렉세이트)",
            ingr_name=[{"kor": "메토트렉세이트", "eng": "", "amount": "", "dur_code": "M000002"}],
        )

    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.post(
        "/drugs/match-names", json={"names": ["메토트렉세이트정"]}, headers=headers
    )
    assert res.status_code == 200
    result = res.json()[0]
    assert result["matched"]["id"] == str(precise.id)


# --------------------------------------------------------------------------- #
# POST /drugs/ocr — 서버 OCR (tesseract 호출은 mock, 이미지는 저장 안 함)        #
# --------------------------------------------------------------------------- #

_OCR_SAMPLE_TEXT = "OO약국\n아스피린정100mg\n1일 3회\n타이레놀정\n500mg\n용법: 식후 30분\n"


def test_extract_candidates_ports_dart_regex():
    """서버 후보 추출이 Flutter _extractCandidates와 같은 규칙인지 (제형+용량 병합 포함)."""
    got = extract_candidates(_OCR_SAMPLE_TEXT)
    assert "아스피린정100mg" in got
    assert "타이레놀정500mg" in got  # "타이레놀정" + 다음 줄 "500mg" 병합
    assert "1일 3회" not in got  # 제형/용량 패턴 없음
    assert "용법: 식후 30분" not in got


async def test_ocr_match_returns_candidates_and_db_matches(
    client, session_factory, monkeypatch
):
    async with session_factory() as session:
        drug = await make_drug(session, "아스피린정100밀리그램")

    monkeypatch.setattr(drugs_api, "run_ocr", lambda _data: _OCR_SAMPLE_TEXT)

    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/drugs/ocr",
        files={"image": ("rx.jpg", b"\xff\xd8\xff\xe0fake-jpeg-bytes", "image/jpeg")},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert "아스피린정100mg" in body["candidates"]
    aspirin = next(
        m for m in body["matches"] if m["queried_name"] == "아스피린정100mg"
    )
    assert aspirin["matched"] is not None
    assert aspirin["matched"]["id"] == str(drug.id)


async def test_ocr_match_requires_auth(client):
    res = await client.post(
        "/drugs/ocr",
        files={"image": ("rx.jpg", b"fake", "image/jpeg")},
    )
    assert res.status_code in (401, 403)


async def test_ocr_match_rejects_non_image(client, monkeypatch):
    monkeypatch.setattr(drugs_api, "run_ocr", lambda _data: "")
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/drugs/ocr",
        files={"image": ("notes.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert res.status_code == 415


async def test_ocr_match_rejects_oversized_image(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(drugs_api, "run_ocr", lambda _data: "")
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    big = b"\xff\xd8" + b"0" * (settings.OCR_MAX_IMAGE_BYTES + 1)
    res = await client.post(
        "/drugs/ocr",
        files={"image": ("big.jpg", big, "image/jpeg")},
        headers=headers,
    )
    assert res.status_code == 413


async def test_ocr_match_surfaces_ocr_engine_failure(client, monkeypatch):
    def _boom(_data):
        raise OcrError("서버에 OCR 엔진이 설치되어 있지 않습니다.")

    monkeypatch.setattr(drugs_api, "run_ocr", _boom)
    token = await register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/drugs/ocr",
        files={"image": ("rx.jpg", b"\xff\xd8fake", "image/jpeg")},
        headers=headers,
    )
    assert res.status_code == 503
