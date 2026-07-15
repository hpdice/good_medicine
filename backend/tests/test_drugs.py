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
