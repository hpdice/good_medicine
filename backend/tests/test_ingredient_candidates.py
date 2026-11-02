"""성분명 후보 수집(candidate_ingredient_names)과 성분명 → DUR 성분코드 해소(make_ingredient_resolver)."""
from app.services.public_data_service.helpers import (
    candidate_ingredient_names,
    make_ingredient_resolver,
)


def test_collects_from_jsonb_main_ingr_and_item_name_parentheses_in_order():
    names = candidate_ingredient_names(
        [{"kor": "와파린나트륨"}, {"kor": ""}, None],
        "[M040702]와파린나트륨/[M222222]아세트아미노펜",
        "쿠파린정2밀리그램(와파린나트륨)",
    )
    assert names == ["와파린나트륨", "와파린나트륨", "아세트아미노펜", "와파린나트륨"]


def test_parentheses_are_split_on_separators_and_blank_parts_dropped():
    assert candidate_ingredient_names(None, None, "복합제(케토프로펜, 이부프로펜/ ·카페인)") == ["케토프로펜", "이부프로펜", "카페인"]


def test_square_and_fullwidth_brackets_are_also_read():
    assert candidate_ingredient_names(None, None, "뉴펜겔[케토프로펜]") == ["케토프로펜"]
    assert candidate_ingredient_names(None, None, "뉴펜겔（케토프로펜）") == ["케토프로펜"]

_RESOLVE = make_ingredient_resolver([
    ("트리메부틴", "D1"), ("칸데사르탄실렉세틸", "D2"), ("에스암로디핀", "D3"), ("니코틴", "D4"), ("니코틴산", "D5"),
    ("포비돈요오드", "D6"), ("미분화 시클레소니드", "D7"), ("시클레소니드", "D10"), ("부데소니드", "D8"), ("요오드", "D9"),
])


def test_resolver_matches_salt_and_ester_forms():
    assert _RESOLVE("트리메부틴말레산염") == "D1"
    assert _RESOLVE("칸데사르탄") == "D2"
    assert _RESOLVE("에스암로디핀니코틴산염") == "D3"  # 염 이름에 다른 성분명(니코틴)이 들어 있어도 염이면 같은 성분


def test_resolver_rejects_prefix_that_names_a_different_substance():
    """실제로 났던 오매칭 — 접두는 맞지만 남는 부분이 다른 물질이다."""
    assert _RESOLVE("포비돈") is None  # 점안액 윤활제 ≠ 포비돈요오드(소독제)
    assert _RESOLVE("미분화") is None
    assert _RESOLVE("미분화부데소니드") is None  # ≠ 미분화 시클레소니드
    assert _RESOLVE("니코틴산아미드") is None  # 비타민 B3 ≠ 니코틴·니코틴산
