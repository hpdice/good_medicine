"""같은 성분인데 DUR 코드가 둘인 경우 — 규칙이 어느 코드에 붙어 있어도 판정한다.

실측(2026-11-05): DUR 조회표에 한글명이 같은 코드 묶음이 10개 있고 규칙이 코드마다 나뉘어 있다(케토롤락: 병용금기 34건은
D000274, 노인주의는 D001289). 한쪽 코드만 받은 약은 다른 쪽 규칙을 놓쳤다 — 펜타미딘 D001456 품목 + 할로페리돌이 safe."""
from sqlalchemy import select

from app.models.dur_ingredient_master import DurIngredientMaster
from app.models.dur_ingredient_rule import DurIngredientContraindication
from app.services.drug_service import ingredient_alias_map
from tests.factories import (
    make_drug,
    make_ingr_age_caution,
    make_ingr_contraindication,
    register_and_login,
    register_and_login_with_profile,
)

KETO_A, KETO_B, IBU = "D900274", "D901289", "D900363"


def test_alias_map_groups_same_name_and_mix_type():
    aliases = ingredient_alias_map([
        ("D2", "케토롤락", "단일"), ("D1", "케토롤락", "단일"),
        ("D3", "브리모니딘 타르타르산염", "단일"), ("D4", "브리모니딘타르타르산염", "단일"),  # 공백만 다르다
        ("D5", "클린다마이신", "단일"), ("D6", "클린다마이신", "복합"),  # 단일/복합이 다르면 다른 것
        ("D7", "이부프로펜", "단일"), ("D8", None, "단일"), ("D9", None, "단일"),
    ])
    assert aliases == {"D1": "D1", "D2": "D1", "D3": "D3", "D4": "D3"}


async def _master(session, *rows):
    for code, kor in rows:
        session.add(DurIngredientMaster(ingr_code=code, ingr_kor=kor, ingr_eng=None, mix_type="단일"))
    await session.commit()


async def _check(client, headers, *drugs):
    res = await client.post("/analysis/quick-check", json={"drug_ids": [str(d.id) for d in drugs]}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def test_contraindication_on_sibling_code_is_found(client, session_factory):
    async with session_factory() as session:
        await _master(session, (KETO_A, "케토롤락"), (KETO_B, "케토롤락"), (IBU, "이부프로펜"))
        keto = await make_drug(session, "케톨민주(케토롤락트로메타민)", ingredients=[(KETO_B, "케토롤락")])
        ibu = await make_drug(session, "이부펜정", ingredients=[(IBU, "이부프로펜")])
        await make_ingr_contraindication(session, KETO_A, IBU, "케토롤락", "이부프로펜",
                                         prohibit_content="중증의 위장관계 이상반응")

    body = await _check(client, {"Authorization": f"Bearer {await register_and_login(client)}"}, keto, ibu)
    assert body["risk_level"] == "critical"
    assert [f["mechanism"] for f in body["findings"]] == ["중증의 위장관계 이상반응"]

    async with session_factory() as session:  # 대표 코드로 바꾼 건 응답용 사본뿐 — 규칙 행은 그대로
        rule = (await session.execute(select(DurIngredientContraindication))).scalar_one()
        assert {rule.ingr_code_a, rule.ingr_code_b} == {KETO_A, IBU}


async def test_same_ingredient_under_two_codes_is_one_duplicate(client, session_factory):
    async with session_factory() as session:
        await _master(session, (KETO_A, "케토롤락"), (KETO_B, "케토롤락"))
        one = await make_drug(session, "케토라신정", ingredients=[(KETO_A, "케토롤락")])
        two = await make_drug(session, "케톨민주", ingredients=[(KETO_B, "케토롤락")])

    body = await _check(client, {"Authorization": f"Bearer {await register_and_login(client)}"}, one, two)
    assert body["risk_level"] == "caution"
    assert [f["interaction_type"] for f in body["findings"]] == ["duplicate_ingredient"]
    assert "케토롤락" in body["findings"][0]["mechanism"]


async def test_elderly_rule_on_sibling_code_is_found(client, session_factory):
    async with session_factory() as session:
        await _master(session, (KETO_A, "케토롤락"), (KETO_B, "케토롤락"))
        keto = await make_drug(session, "케토라신정", ingredients=[(KETO_A, "케토롤락")])
        await make_ingr_age_caution(session, KETO_B, "elderly_caution", ingr_kor="케토롤락")

    token = await register_and_login_with_profile(client, birth_year=1950)
    body = await _check(client, {"Authorization": f"Bearer {token}"}, keto)
    assert [a["rule_type"] for a in body["age_cautions"]] == ["elderly_caution"]


async def test_codes_without_shared_name_stay_separate(client, session_factory):
    async with session_factory() as session:
        await _master(session, (KETO_A, "케토롤락"), (KETO_B, "케토롤락트로메타민"))
        keto = await make_drug(session, "케톨민주", ingredients=[(KETO_B, "케토롤락트로메타민")])
        ibu = await make_drug(session, "이부펜정", ingredients=[(IBU, "이부프로펜")])
        await make_ingr_contraindication(session, KETO_A, IBU)

    body = await _check(client, {"Authorization": f"Bearer {await register_and_login(client)}"}, keto, ibu)
    assert body["risk_level"] == "safe"


async def _names(session, *codes):
    from app.services.drug_service import DrugService

    return await DrugService(session).get_ingredient_kor_for_codes(set(codes))


async def test_ingredient_name_comes_from_master_not_from_row_order(session_factory):
    """약마다 같은 코드에 다른 이름(염·수화물 표기)이 붙어 있어도 마스터 이름이 항상 나온다(모르핀염산염수화물 → 모르핀)."""
    async with session_factory() as session:
        await _master(session, ("D900006", "모르핀"))
        await make_drug(session, "모르핀염산염주", ingredients=[("D900006", "모르핀염산염수화물")])
        await make_drug(session, "모르핀황산염정", ingredients=[("D900006", "모르핀황산염수화물")])
    for _ in range(5):  # 되풀이해도 같다
        async with session_factory() as session:
            assert await _names(session, "D900006") == {"D900006": "모르핀"}


async def test_ingredient_name_for_alias_group_uses_representative_code(session_factory):
    async with session_factory() as session:
        await _master(session, (KETO_A, "케토롤락"), (KETO_B, "케토롤락"))
        await make_drug(session, "케톨민주", ingredients=[(KETO_B, "케토롤락트로메타민")])
    async with session_factory() as session:
        assert await _names(session, KETO_A) == {KETO_A: "케토롤락"}


async def test_ingredient_name_falls_back_to_shortest_attached_name(session_factory):
    """마스터에 없는 코드는 약에 맺힌 이름 중 가장 짧은 것 — 순서와 무관하게 같은 이름."""
    async with session_factory() as session:
        await make_drug(session, "가정", ingredients=[("D900777", "베타성분염수화물")])
        await make_drug(session, "나정", ingredients=[("D900777", "베타성분")])
        await make_drug(session, "다정", ingredients=[("D900777", "베타성분수화물")])
    for _ in range(5):
        async with session_factory() as session:
            assert await _names(session, "D900777") == {"D900777": "베타성분"}
