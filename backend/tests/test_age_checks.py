from datetime import date

from app.services.analysis_service import _age_taboo_applies
from tests.factories import (
    make_drug,
    make_ingr_age_caution,
    register_and_login_with_profile,
)


def _birth_year_for_age(age: int) -> int:
    return date.today().year - age


# ---------- 특정연령대금기·노인주의 ----------

async def test_age_taboo_detected_for_young_user(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트연령금기정", ingredients=[("D600001", "연령금기성분")])
        drug_b = await make_drug(session, "테스트동반정A")
        await make_ingr_age_caution(
            session, "D600001", "age_taboo",
            prohibit_content="3세 미만 소아에 사용하지 말 것",
            age_threshold=3, age_unit="세", age_direction="미만",
        )

    token = await register_and_login_with_profile(client, birth_year=_birth_year_for_age(2))
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "critical"
    assert body["age_taboo_count"] == 1
    assert body["age_cautions"][0]["rule_type"] == "age_taboo"


async def test_age_taboo_not_applied_above_threshold(client, session_factory):
    """나이가 기준 밖이면(3세 미만 규칙, 사용자는 10세) 판정에 안 걸린다."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트연령금기정B", ingredients=[("D600002", "연령금기성분B")])
        drug_b = await make_drug(session, "테스트동반정B")
        await make_ingr_age_caution(
            session, "D600002", "age_taboo",
            age_threshold=3, age_unit="세", age_direction="미만",
        )

    token = await register_and_login_with_profile(client, birth_year=_birth_year_for_age(10))
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["age_taboo_count"] == 0


async def test_age_taboo_skipped_when_threshold_unparsed(client, session_factory):
    """PROHBT_CONTENT에서 숫자 기준을 못 뽑은 규칙(대다수)은 조용히 스킵된다."""
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트연령금기정C", ingredients=[("D600003", "연령금기성분C")])
        drug_b = await make_drug(session, "테스트동반정C")
        await make_ingr_age_caution(
            session, "D600003", "age_taboo",
            prohibit_content="영아에 대해 독성이 빈번하게 발생",
        )  # age_threshold/unit/direction 전부 None

    token = await register_and_login_with_profile(client, birth_year=_birth_year_for_age(1))
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["age_taboo_count"] == 0


async def test_elderly_caution_detected_for_elderly_user(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트노인주의정", ingredients=[("D600004", "노인주의성분")])
        drug_b = await make_drug(session, "테스트동반정D")
        await make_ingr_age_caution(session, "D600004", "elderly_caution")

    token = await register_and_login_with_profile(client, birth_year=_birth_year_for_age(70))
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "caution"
    assert body["elderly_caution_count"] == 1


async def test_elderly_caution_not_applied_under_65(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트노인주의정B", ingredients=[("D600005", "노인주의성분B")])
        drug_b = await make_drug(session, "테스트동반정E")
        await make_ingr_age_caution(session, "D600005", "elderly_caution")

    token = await register_and_login_with_profile(client, birth_year=_birth_year_for_age(40))
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["elderly_caution_count"] == 0
    assert body["risk_level"] == "safe"


async def test_no_age_check_when_birth_year_not_set(client, session_factory):
    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트노인주의정C", ingredients=[("D600006", "노인주의성분C")])
        drug_b = await make_drug(session, "테스트동반정F")
        await make_ingr_age_caution(session, "D600006", "elderly_caution")

    token = await register_and_login_with_profile(client)  # birth_year 미입력
    headers = {"Authorization": f"Bearer {token}"}
    res = await client.post(
        "/analysis/quick-check",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["age_cautions"] == []


def test_age_taboo_week_unit_is_compared_in_years():
    """AGE_BASE '4주 미만'(성분정보) — 출생연도만 있어 올해 태어난 사용자(0세)만 해당한다."""
    assert _age_taboo_applies(0, 4, "주", "미만") is True
    assert _age_taboo_applies(1, 4, "주", "미만") is False
    assert _age_taboo_applies(1, 24, "개월", "미만") is True
    assert _age_taboo_applies(2, 24, "개월", "미만") is False
