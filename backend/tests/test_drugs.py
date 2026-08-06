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
