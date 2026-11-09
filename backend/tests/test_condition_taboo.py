"""건강 상태 금기 — 허가사항 "다음 환자에는 투여하지 말 것" 항목에 사용자의 건강 상태가 글자 그대로 있으면 금기."""
from app.services.condition_taboo import contraindication_items, find_condition_taboo
from tests.factories import make_drug, register_and_login_with_profile

PROFESSIONAL = """1. 다음 환자에는 투여하지 말 것.
1) 이 약 또는 이 약의 구성성분에 과민반응이 있는 환자
2) 기관지 점액 분비 증가 환자
3) 중증의 간장애 환자
2. 다음 환자에는 신중히 투여할 것.
1) 중증 심부전 및 중증 신장부전 환자
2) 고혈압 환자
3. 이상반응
1) 소화기계 : 구역, 설사"""

WRAPPED = """1. 다음 환자에는 투여하지 말 것.
1) 소화성 궤양 환자(위장관 출혈이 있거나
   병력이 있는 환자)
2) 천식 환자
2. 다음 환자에는 신중히 투여할 것."""

CONSUMER = """다음과 같은 사람은 이 약을 복용하지 마십시오.
녹내장이 있는 사람
전립선 비대로 소변이 잘 나오지 않는 사람
이 약을 복용하기 전에 의사 또는 약사와 상의하십시오."""


def test_items_are_only_the_contraindication_list():
    assert contraindication_items(PROFESSIONAL) == [
        "이 약 또는 이 약의 구성성분에 과민반응이 있는 환자", "기관지 점액 분비 증가 환자", "중증의 간장애 환자",
    ]  # '신중히 투여할 것'의 고혈압·신부전은 금기가 아니라 빠진다


def test_wrapped_item_lines_are_joined():
    items = contraindication_items(WRAPPED)
    assert items[0] == "소화성 궤양 환자(위장관 출혈이 있거나 병력이 있는 환자)" and items[1] == "천식 환자"


def test_consumer_style_without_bullets_uses_each_line():
    assert "녹내장이 있는 사람" in contraindication_items(CONSUMER)


def test_no_heading_or_empty_text_gives_nothing():
    assert contraindication_items(None) == [] and contraindication_items("") == []
    assert contraindication_items("1. 이상반응\n1) 두통") == []


def test_condition_matches_literally_and_returns_the_original_sentence():
    assert find_condition_taboo(PROFESSIONAL, ["간장애"]) == [("간장애", "중증의 간장애 환자")]
    assert find_condition_taboo(WRAPPED, [" 천식 "]) == [("천식", "천식 환자")]


def test_condition_in_caution_only_section_is_not_a_taboo():
    assert find_condition_taboo(PROFESSIONAL, ["고혈압"]) == []  # '신중히 투여할 것'에만 있다


def test_spaces_are_ignored_and_synonyms_are_not_expanded():
    assert find_condition_taboo(WRAPPED, ["소화성궤양"]) == [("소화성궤양", "소화성 궤양 환자(위장관 출혈이 있거나 병력이 있는 환자)")]
    assert find_condition_taboo(WRAPPED, ["위궤양"]) == []  # 표현이 다르면 못 찾는다(알려진 한계)


def test_condition_inside_another_word_is_not_a_match():
    text = "1. 다음 환자에는 투여하지 말 것." + chr(10) + "1) 폐고혈압에 의한 우심부전 환자" + chr(10) + "2) 중증간장애 환자"
    assert find_condition_taboo(text, ["고혈압"]) == []  # 폐고혈압은 고혈압이 아니다
    assert find_condition_taboo(text, ["간장애"]) == [("간장애", "중증간장애 환자")]  # 중증 표시는 같은 병이다


def test_a_sentence_that_merely_contains_the_phrase_does_not_start_a_list():
    text = ("1. 일반적 주의" + chr(10) + "이 약은 다음 환자에게 투여하지 않는다." + chr(10) + "1) 천식 환자")
    assert contraindication_items(text) == []  # 줄 맨 앞이 "다음"인 제목만 목록의 시작이다


def test_condition_only_in_a_parenthetical_reason_is_not_a_match():
    text = "1. 다음 환자에는 투여하지 말 것." + chr(10) + "1) 크롬친화세포종 환자(종양으로 인해 고혈압을 유발할 수 있다.)"
    assert find_condition_taboo(text, ["고혈압"]) == []
    assert find_condition_taboo(text, ["크롬친화세포종"]) == [("크롬친화세포종", "크롬친화세포종 환자(종양으로 인해 고혈압을 유발할 수 있다.)")]


def test_single_character_conditions_are_ignored():
    assert find_condition_taboo(PROFESSIONAL, ["간"]) == []


async def test_quick_check_marks_condition_taboo_as_critical(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "테스트건강금기정")
        drug.atpn_qesitm = PROFESSIONAL
        await session.commit()
        other = await make_drug(session, "테스트무관정")
    token = await register_and_login_with_profile(client, health_conditions=["간장애", "고혈압"])
    res = await client.post(
        "/analysis/quick-check", json={"drug_ids": [str(drug.id), str(other.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = res.json()
    assert body["risk_level"] == "critical" and body["condition_taboo_count"] == 1
    taboo = body["condition_taboos"][0]
    assert (taboo["condition"], taboo["sentence"]) == ("간장애", "중증의 간장애 환자")
    assert "allergy_conflicts" not in body  # 알레르기 판정은 없다


async def test_quick_check_without_conditions_skips_the_check(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "테스트건강금기정B")
        drug.atpn_qesitm = PROFESSIONAL
        await session.commit()
    token = await register_and_login_with_profile(client)
    res = await client.post(
        "/analysis/quick-check", json={"drug_ids": [str(drug.id)]}, headers={"Authorization": f"Bearer {token}"},
    )
    assert res.json()["condition_taboos"] == [] and res.json()["risk_level"] == "safe"
