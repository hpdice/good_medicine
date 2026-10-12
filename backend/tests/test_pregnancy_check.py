"""DUR 임부금기 — 임신 중으로 등록한 사용자에게만, 품목(ITEM_SEQ) 단위로 판정한다."""
from tests.factories import make_drug, make_pregnancy_taboo, register_and_login_with_profile


async def _quick_check(client, token, *drugs):
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(d.id) for d in drugs]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    return res.json()


async def test_pregnancy_taboo_detected_as_critical(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트임부금기정")
        drug_b = await make_drug(session, "테스트동반임부정A")
        await make_pregnancy_taboo(
            session, drug_a, prohibit_content="1등급 태아독성 보고", remark="경구",
        )

    token = await register_and_login_with_profile(client, is_pregnant=True)
    body = await _quick_check(client, token, drug_a, drug_b)

    assert body["risk_level"] == "critical"
    assert body["pregnancy_taboo_count"] == 1
    caution = body["pregnancy_cautions"][0]
    assert caution["drug_id"] == str(drug_a.id)
    assert caution["prohibit_content"] == "1등급 태아독성 보고"
    assert caution["remark"] == "경구"


async def test_pregnancy_taboo_ignored_when_not_pregnant(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트임부금기정B")
        drug_b = await make_drug(session, "테스트동반임부정B")
        await make_pregnancy_taboo(session, drug_a)

    token = await register_and_login_with_profile(client, is_pregnant=False)
    body = await _quick_check(client, token, drug_a, drug_b)

    assert body["pregnancy_cautions"] == []
    assert body["pregnancy_taboo_count"] == 0
    assert body["risk_level"] == "safe"


async def test_pregnancy_taboo_ignored_when_profile_unset(client, session_factory):
    """임신 여부를 입력한 적 없는 사용자는 판정에서 스킵(기존 동작 그대로)."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트임부금기정C")
        drug_b = await make_drug(session, "테스트동반임부정C")
        await make_pregnancy_taboo(session, drug_a)

    token = await register_and_login_with_profile(client)
    body = await _quick_check(client, token, drug_a, drug_b)

    assert body["pregnancy_cautions"] == []
    assert body["risk_level"] == "safe"


async def test_pregnancy_taboo_is_item_level_not_ingredient_level(client, session_factory):
    """같은 성분이라도 규칙이 걸린 품목만 경고한다(외용제 등 비고 범위 밖 품목 오탐 방지)."""
    async with session_factory() as session:
        oral = await make_drug(session, "테스트경구정", ingredients=[("D700100", "공통성분")])
        topical = await make_drug(session, "테스트외용겔", ingredients=[("D700100", "공통성분")])
        await make_pregnancy_taboo(session, oral, ingr_code="D700100", remark="경구")

    token = await register_and_login_with_profile(client, is_pregnant=True)
    body = await _quick_check(client, token, oral, topical)

    assert [c["drug_id"] for c in body["pregnancy_cautions"]] == [str(oral.id)]


async def test_pregnancy_taboo_works_without_ingredient_resolution(client, session_factory):
    """성분코드 미해소 약(drug_ingredients 없음)도 item_seq로 곧바로 걸린다."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트미해소임부정")  # ingredients 없음
        drug_b = await make_drug(session, "테스트동반임부정D")
        await make_pregnancy_taboo(session, drug_a)

    token = await register_and_login_with_profile(client, is_pregnant=True)
    body = await _quick_check(client, token, drug_a, drug_b)

    assert body["pregnancy_taboo_count"] == 1


async def test_multi_ingredient_rows_merge_into_one_caution(client, session_factory):
    async with session_factory() as session:
        combo = await make_drug(session, "테스트복합임부정")
        other = await make_drug(session, "테스트동반임부정E")
        await make_pregnancy_taboo(session, combo, ingr_code="D700201", prohibit_content="성분1 사유")
        await make_pregnancy_taboo(session, combo, ingr_code="D700202", prohibit_content="성분2 사유")

    token = await register_and_login_with_profile(client, is_pregnant=True)
    body = await _quick_check(client, token, combo, other)

    assert body["pregnancy_taboo_count"] == 1
    assert body["pregnancy_cautions"][0]["prohibit_content"] == "성분1 사유\n성분2 사유"


async def test_is_pregnant_roundtrip_and_encrypted(client, session_factory):
    """PATCH로 저장한 값이 GET /users/me로 돌아오고, DB에는 평문이 아니다."""
    from sqlalchemy import select

    from app.models.user import User

    token = await register_and_login_with_profile(client, is_pregnant=True)
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/users/me", headers=headers)).json()["is_pregnant"] is True

    await client.patch("/users/me", json={"is_pregnant": False}, headers=headers)
    assert (await client.get("/users/me", headers=headers)).json()["is_pregnant"] is False

    async with session_factory() as session:
        stored = (await session.execute(select(User.pregnancy_encrypted))).scalars().all()
    assert stored and all(v and v not in ("true", "false") for v in stored if v)
