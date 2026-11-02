"""성분명 후보 수집(candidate_ingredient_names) — 약 하나의 이름 세 군데에서 성분명을 모은다."""
from app.services.public_data_service.helpers import candidate_ingredient_names


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
