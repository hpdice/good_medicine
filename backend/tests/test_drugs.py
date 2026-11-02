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


async def test_match_names_prefers_domestic_product_over_export_only(client, session_factory):
    """수출용 품목은 국내 품목과 매칭키가 같다('판콜에이내복액') — 브랜드명으로 찾으면 국내 품목이 확정돼야 한다."""
    async with session_factory() as session:
        await make_drug(session, "판콜에이내복액(Pancold A Oral Liquid 30mL)(수출용)")
        domestic = await make_drug(session, "판콜에이내복액")
    token = await register_and_login(client)
    res = await client.post(
        "/drugs/match-names", json={"names": ["판콜에이", "판콜에이내복액"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert [r["matched"]["id"] for r in res.json()] == [str(domestic.id)] * 2


# --------------------------------------------------------------------------- #
# POST /drugs/ocr — 서버 OCR (tesseract 호출은 mock, 이미지는 저장 안 함)        #
# --------------------------------------------------------------------------- #

_OCR_SAMPLE_TEXT = "OO약국\n아스피린정100mg\n1일 3회\n타이레놀정\n500mg\n용법: 식후 30분\n"


def test_extract_candidates_joins_split_dosage_and_skips_instructions():
    """이름 줄 다음의 순수 용량 줄을 합치고('타이레놀정' + '500mg'), 복용 안내 문장은 후보로 넣지 않는다."""
    got = extract_candidates(_OCR_SAMPLE_TEXT)
    assert "아스피린정100mg" in got
    assert "타이레놀정500mg" in got  # "타이레놀정" + 다음 줄 "500mg" 병합
    assert "1일 3회" not in got  # 제형/용량 패턴 없음
    assert "용법: 식후 30분" not in got


async def test_match_names_suggests_similar_drug_for_ocr_typo(client, session_factory):
    """OCR이 한 글자 틀린 이름('렉'↔'랙')은 자동 확정하지 않고 '유사 약품'으로만 내려준다."""
    async with session_factory() as session:
        target = await make_drug(session, "신플랙스세이프정500/20밀리그램")
        await make_drug(session, "타이레놀정500밀리그램")
    token = await register_and_login(client)
    res = await client.post(
        "/drugs/match-names",
        json={"names": ["신플렉스세이프정", "가나다라마정"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    typo, garbage = res.json()
    assert typo["matched"] is None  # 오인식을 자동으로 확정하면 안 된다
    assert [a["id"] for a in typo["alternatives"]] == [str(target.id)]
    assert garbage["matched"] is None and garbage["alternatives"] == []  # 닮은 게 없으면 억지로 안 낸다


def test_extract_candidates_keeps_digits_inside_name():
    """이름 가운데 숫자('8시간')에서 끊겨 '시간이알서방정' 조각만 남던 버그."""
    got = extract_candidates("아니스펜8시간이알서방정(아..  1회투약량 1\n1회투약량1 1일투여횟수2\n")
    assert "아니스펜8시간이알서방정" in got
    assert not any(c.startswith("1") or "투약" in c for c in got)


def test_extract_candidates_drops_generic_form_fragments():
    """줄이 잘려 제형·서방 설명어만 읽힌 조각은 약 이름이 아니다 — 엉뚱한 약에 매칭되던 버그."""
    text = "신플랙스세이프정  1회투약량1\nEM 서방정\n알서방정\n시간이알서방정\n뉴부틴서방정(말레인산트리메..\n"
    got = extract_candidates(text)
    assert "신플랙스세이프정" in got
    assert "뉴부틴서방정" in got
    for fragment in ("서방정", "알서방정", "시간이알서방정"):
        assert fragment not in got


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


async def test_large_response_is_gzip_compressed(client, session_factory):
    """허가사항 전문(수만 자)이 든 응답은 gzip으로 내려간다 — 복약함 13종이 198KB→52KB."""
    async with session_factory() as session:
        drug = await make_drug(session, "긴설명정")
        drug.atpn_qesitm = "1) 이 약 또는 이 약의 구성성분에 과민반응 환자\n" * 800
        await session.commit()

    token = await register_and_login(client)
    res = await client.get(
        f"/drugs/{drug.id}",
        headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "gzip"},
    )
    assert res.status_code == 200
    assert res.headers.get("content-encoding") == "gzip"
    assert res.json()["atpn_qesitm"].count("과민반응") == 800  # 압축을 풀면 원문 그대로
