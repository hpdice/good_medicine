import uuid

from sqlalchemy import select

from app.core.encryption import get_encryptor
from app.models.medicine_box import MedicineBoxEntry
from tests.factories import (
    make_contraindication,
    make_drug,
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


async def test_medicine_box_entry_encrypted_at_rest(client, session_factory):
    """복약 정보(어떤 약·용량·메모)는 payload_encrypted 한 컬럼에만 저장되고
    평문 drug_id 컬럼은 존재하지 않는다. 응답에는 복호화된 평문이 나온다."""
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    res = await client.post(
        "/medicine-box",
        json={"drug_id": str(drug.id), "dosage_per_intake": "1정", "notes": "아침 식후 복용"},
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["drug"]["id"] == str(drug.id)
    assert res.json()["notes"] == "아침 식후 복용"

    async with session_factory() as session:
        row = (await session.execute(select(MedicineBoxEntry))).scalar_one()
        assert not hasattr(row, "drug_id")
        assert "아침" not in row.payload_encrypted  # 원문이 암호문에 노출되지 않음
        payload = get_encryptor().decrypt(row.payload_encrypted)
        assert payload["drug_id"] == str(drug.id)
        assert payload["notes"] == "아침 식후 복용"


async def test_medicine_box_reminder_fields_round_trip(client, session_factory):
    """intake_times/reminder_enabled은 payload_encrypted 안 논리 필드로 저장·복호화된다."""
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    res = await client.post(
        "/medicine-box",
        json={
            "drug_id": str(drug.id),
            "intake_times": ["08:00", "20:00"],
            "reminder_enabled": True,
        },
        headers=headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["intake_times"] == ["08:00", "20:00"]
    assert body["reminder_enabled"] is True

    entry_id = body["id"]
    patch_res = await client.patch(
        f"/medicine-box/{entry_id}", json={"reminder_enabled": False}, headers=headers
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["reminder_enabled"] is False
    assert patch_res.json()["intake_times"] == ["08:00", "20:00"]  # 다른 필드는 유지


async def test_medicine_box_rejects_invalid_intake_time_format(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    res = await client.post(
        "/medicine-box",
        json={"drug_id": str(drug.id), "intake_times": ["25:00"]},
        headers=headers,
    )
    assert res.status_code == 422


async def test_add_nonexistent_drug_rejected(client, session_factory):
    headers = await _auth_headers(client)
    res = await client.post(
        "/medicine-box", json={"drug_id": str(uuid.uuid4())}, headers=headers
    )
    assert res.status_code == 404


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


async def test_quick_check_effect_group_across_dur_seq_same_series(client, session_factory):
    """실제 원본처럼 성분마다 dur_seq가 달라도 같은 효능군·계열이면 효능군중복 (dur_seq로 묶던 결함의 회귀)."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "덱시프로펜정", ingredients=[("D000086", "덱시부프로펜")])
        drug_b = await make_drug(session, "부루펜정", ingredients=[("D000363", "이부프로펜")])
        await make_ingr_effect_group(session, [("D000086", "덱시부프로펜")], dur_seq="2401",
                                     effect_name="해열진통소염제", sers_name="비스테로이드성 소염제")
        await make_ingr_effect_group(session, [("D000363", "이부프로펜")], dur_seq="2420",
                                     effect_name="해열진통소염제", sers_name="비스테로이드성 소염제")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    body = res.json()
    assert body["risk_level"] == "caution"
    assert body["duplicate_effect_group_count"] == 1
    assert body["findings"][0]["mechanism"] == "효능군 중복: 해열진통소염제 · 비스테로이드성 소염제"


async def test_quick_check_effect_group_different_series_not_duplicate(client, session_factory):
    """같은 효능군이어도 계열이 다르면(ARB + CCB) 중복이 아니다 — 표준 병용요법에 경고하지 않는다."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "코자정", ingredients=[("D000300", "로사르탄")])
        drug_b = await make_drug(session, "노바스크정", ingredients=[("D000301", "암로디핀")])
        await make_ingr_effect_group(session, [("D000300", "로사르탄")], dur_seq="3001",
                                     effect_name="혈압강하작용의약품", sers_name="ARB")
        await make_ingr_effect_group(session, [("D000301", "암로디핀")], dur_seq="3002",
                                     effect_name="혈압강하작용의약품", sers_name="CCB:Dihydro pyridines ")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    body = res.json()
    assert body["risk_level"] == "safe"
    assert body["duplicate_effect_group_count"] == 0


async def test_quick_check_same_ingredient_duplicate_without_effect_group(client, session_factory):
    """효능군에 없는 성분(레비티라세탐)도 같은 성분 두 약품이면 caution."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "레비라정750", ingredients=[("D000510", "레비티라세탐")])
        drug_b = await make_drug(session, "큐팜정750", ingredients=[("D000510", "레비티라세탐")])

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "caution"
    assert body["duplicate_ingredient_count"] == 1
    assert body["duplicate_effect_group_count"] == 0
    assert body["findings"][0]["interaction_type"] == "duplicate_ingredient"
    assert "레비티라세탐" in body["findings"][0]["mechanism"]


async def test_quick_check_same_ingredient_wins_over_effect_group(client, session_factory):
    """효능군에도 있는 같은 성분 쌍은 duplicate_ingredient 1건만 남는다."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "크레스토정10", ingredients=[("D000001", "로수바스타틴")])
        drug_b = await make_drug(session, "크레스토정20", ingredients=[("D000001", "로수바스타틴")])
        await make_ingr_effect_group(
            session, [("D000001", "로수바스타틴")], dur_seq="1", effect_name="지질저하제",
        )

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    body = res.json()
    assert body["duplicate_ingredient_count"] == 1
    assert body["duplicate_effect_group_count"] == 0
    assert len(body["findings"]) == 1


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
