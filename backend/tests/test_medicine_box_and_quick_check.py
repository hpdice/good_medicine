from tests.factories import make_contraindication, make_drug, make_effect_group, register_and_login


async def _auth_headers(client) -> dict:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def test_add_drug_to_medicine_box(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    res = await client.post("/medicine-box", json={"drug_id": str(drug.id)}, headers=headers)
    assert res.status_code == 201
    assert res.json()["drug"]["id"] == str(drug.id)


async def test_add_same_drug_twice_rejected(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    first = await client.post("/medicine-box", json={"drug_id": str(drug.id)}, headers=headers)
    assert first.status_code == 201

    second = await client.post("/medicine-box", json={"drug_id": str(drug.id)}, headers=headers)
    assert second.status_code == 409


async def test_list_and_delete_medicine_box_entry(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    add_res = await client.post("/medicine-box", json={"drug_id": str(drug.id)}, headers=headers)
    entry_id = add_res.json()["id"]

    list_res = await client.get("/medicine-box", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    del_res = await client.delete(f"/medicine-box/{entry_id}", headers=headers)
    assert del_res.status_code == 204

    list_res2 = await client.get("/medicine-box", headers=headers)
    assert list_res2.json() == []


async def test_quick_check_detects_contraindication_as_critical(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "경동아스피린장용정", class_name="해열.진통.소염제")
        drug_b = await make_drug(session, "유한메토트렉세이트정", class_name="항악성종양제")
        await make_contraindication(session, drug_a, drug_b, mechanism="혈액학적 독성")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "critical"
    assert body["has_contraindication"] is True
    assert body["contraindicated_count"] == 1
    assert len(body["findings"]) == 1
    assert body["findings"][0]["interaction_type"] == "contraindicated"


async def test_quick_check_detects_duplicate_effect_group_as_caution(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "크레스토정20밀리그램", class_name="동맥경화용제")
        drug_b = await make_drug(session, "크레스토정10밀리그램", class_name="동맥경화용제")
        await make_effect_group(session, [drug_a, drug_b], dur_seq="9001", effect_name="지질저하제")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "caution"
    assert body["has_contraindication"] is False
    assert body["duplicate_effect_group_count"] == 1
    assert body["findings"][0]["interaction_type"] == "duplicate_effect_group"


async def test_quick_check_returns_safe_for_unrelated_drugs(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "가스활명수정")
        drug_b = await make_drug(session, "타이레놀정500밀리그램")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "safe"
    assert body["findings"] == []


async def test_quick_check_requires_at_least_two_drugs(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    res = await client.post(
        "/analysis/quick-check", json={"drug_ids": [str(drug.id)]}, headers=headers
    )
    assert res.status_code == 422
