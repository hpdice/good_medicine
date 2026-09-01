from tests.factories import (
    make_contraindication,
    make_drug,
    make_effect_group,
    make_ingr_contraindication,
    make_ingr_effect_group,
    register_and_login,
)


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


# ---------- 성분(ingredient) 단위 판정 ----------

async def test_quick_check_ingredient_contraindication_critical(client, session_factory):
    """서로 다른 브랜드 약이 각각 한 성분씩 보유 + 그 성분쌍이 금기 → critical.
    품목 단위 drug_interactions에는 이 쌍이 없다(성분 경로만 탐지)."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "코니트라캡슐", ingredients=[("D000762", "이트라코나졸")])
        drug_b = await make_drug(session, "리피스탄정", ingredients=[("D000027", "심바스타틴")])
        await make_ingr_contraindication(
            session, "D000762", "D000027", "이트라코나졸", "심바스타틴",
            prohibit_content="횡문근융해증 위험 증가", risk_tags=["횡문근융해증"],
        )

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "critical"
    assert body["contraindicated_count"] == 1
    assert len(body["findings"]) == 1
    finding = body["findings"][0]
    assert finding["interaction_type"] == "contraindicated"
    assert finding["source"] == "ingredient"
    assert finding["mechanism"] == "횡문근융해증 위험 증가"
    assert "횡문근융해증" in finding["risk_tags"]  # mechanism 문장에서 태그 추출


async def test_quick_check_ingredient_effect_group_caution(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "낙센정", ingredients=[("D000739", "아세클로페낙")])
        drug_b = await make_drug(session, "이지엔정", ingredients=[("D000741", "나프록센")])
        await make_ingr_effect_group(
            session,
            [("D000739", "아세클로페낙"), ("D000741", "나프록센")],
            dur_seq="2463", effect_name="해열진통소염제",
        )

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "caution"
    assert body["duplicate_effect_group_count"] == 1
    assert body["findings"][0]["interaction_type"] == "duplicate_effect_group"
    assert body["findings"][0]["source"] == "ingredient"


async def test_quick_check_dedupes_ingredient_over_residual(client, session_factory):
    """같은 쌍이 성분 규칙 + residual 양쪽에 있으면 finding 1건, source=ingredient 우선."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "브랜드가정", ingredients=[("D111111", "성분가")])
        drug_b = await make_drug(session, "브랜드나정", ingredients=[("D222222", "성분나")])
        await make_contraindication(session, drug_a, drug_b, mechanism="잔여 기전")
        await make_ingr_contraindication(session, "D111111", "D222222", "성분가", "성분나",
                                         prohibit_content="성분 기전")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "critical"
    assert len(body["findings"]) == 1
    assert body["findings"][0]["source"] == "ingredient"
    assert body["findings"][0]["mechanism"] == "성분 기전"


async def test_quick_check_residual_finding_when_drug_unresolved(client, session_factory):
    """성분코드가 없는 약이 낀 쌍은 residual_interactions 폴백으로 잡힌다."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "구약가정")
        drug_b = await make_drug(session, "구약나정")
        await make_contraindication(session, drug_a, drug_b, mechanism="잔여 전용 기전")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "critical"
    assert len(body["findings"]) == 1
    assert body["findings"][0]["source"] == "residual"
    assert body["findings"][0]["mechanism"] == "잔여 전용 기전"


async def test_quick_check_residual_still_checked_when_all_resolved(client, session_factory):
    """회귀: residual 쌍의 약이 나중에 성분코드를 얻어도(성분 규칙은 여전히 없음)
    residual 폴백을 계속 조회해야 한다 — 조건부 스킵 시 safe로 오판했던 버그."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "잔여가정", ingredients=[("D900001", "성분갑")])
        drug_b = await make_drug(session, "잔여나정", ingredients=[("D900002", "성분을")])
        await make_contraindication(session, drug_a, drug_b, mechanism="잔여 기전 A")
        # 성분 규칙(dur_ingredient_contraindications)은 일부러 만들지 않음

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "critical"
    assert body["findings"][0]["source"] == "residual"
