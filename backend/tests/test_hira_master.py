"""심평원 약가마스터 CSV 행 → 적재 행 (순수 함수)."""
from datetime import date

from app.services.public_data_service.helpers import (
    hira_gen_ingredients_from_rows,
    hira_item_gen_codes_from_rows,
    resolve_hira_components,
)


def _std(seq, gen, cancelled="", etc="전문의약품", atc=""):
    return {"품목기준코드": f"{seq} ", "일반명코드(성분명코드)": gen, "취소일자": cancelled,
            "전문일반구분": etc, "국제표준코드(ATC코드)": atc}


def test_item_gen_codes_collapse_packages_and_drop_rows_without_gen_code():
    out = hira_item_gen_codes_from_rows([
        _std("200707750", "249001ATB", atc="A10BF03"),
        _std("200707750", "249001ATB", cancelled="2020-05-25"),  # 같은 품목의 다른 포장
        _std("199903675", ""),                                  # 일반명코드 없음 → 버림
    ])
    assert out == {("200707750", "249001ATB"): {"etc_otc": "전문의약품", "atc_code": "A10BF03", "cancelled_on": None}}


def test_item_gen_code_cancelled_only_when_every_package_is_cancelled():
    out = hira_item_gen_codes_from_rows([
        _std("1", "G1", cancelled="2016-10-25"), _std("1", "G1", cancelled="2020-05-25"),
    ])
    assert out[("1", "G1")]["cancelled_on"] == date(2020, 5, 25)


def _ing(gen, name, strength="10", unit="mg", route="내복"):
    return {"일반명코드": gen, "제형구분코드": "TB", "제형": "정제", "일반명": name, "분류번호": "214",
            "투여": route, "함량": strength, "단위": unit}


def test_gen_ingredients_number_components_in_file_order():
    out = hira_gen_ingredients_from_rows([
        _ing("248100ATB", "emtricitabine", "200"),
        _ing("248100ATB", "rilpivirine hydrochloride (as rilpivirine)", "25"),
        _ing("297400ATB", "estradiol hemihydrate (as estradiol)", "1"),
        _ing("297400ATB", "estradiol hemihydrate (as estradiol)", "2"),  # 같은 이름, 단계별 함량
        _ing("", "빈 코드"),
    ])
    assert sorted(out) == [("248100ATB", 1), ("248100ATB", 2), ("297400ATB", 1), ("297400ATB", 2)]
    assert out[("248100ATB", 2)]["ingr_name"] == "rilpivirine hydrochloride (as rilpivirine)"
    assert (out[("297400ATB", 2)]["strength"], out[("297400ATB", 2)]["unit"], out[("297400ATB", 2)]["route"]) == ("2", "mg", "내복")


_BY_ENG = {
    "morphine": {"D000006"}, "morphine sulfate": {"D001642"}, "tamsulosin": {"D1"}, "clopidogrel": {"D2"},
    "losartan": {"D3"}, "hydrochlorothiazide": {"D4"}, "naproxen": {"D000195", "D000982"},
}
_MIX = {"D000006": "단일", "D001642": "단일", "D1": "단일", "D2": "단일", "D3": "단일", "D4": "단일",
        "D000195": "단일", "D000982": "복합"}


def test_resolve_hira_components_exact_as_part_and_salt_stage():
    assert resolve_hira_components(["clopidogrel bisulfate (as clopidogrel)"], _BY_ENG, _MIX) == ({"D2"}, 1)
    assert resolve_hira_components(["tamsulosin hydrochloride"], _BY_ENG, _MIX) == ({"D1"}, 2)
    # 제형 설명어도 뗀다(타이레놀8시간이알서방정 'acetaminophen(encapsulated)') — 숫자가 붙은 설명은 그대로 남아 안 맞는다
    assert resolve_hira_components(["tamsulosin(encapsulated)"], _BY_ENG, _MIX) == ({"D1"}, 2)
    assert resolve_hira_components(["tamsulosin(enteric coated 215mg)"], _BY_ENG, _MIX) is None
    # 염이 다른 DUR 코드(모르핀황산염)까지 붙지 않는다 — DUR 쪽 이름에서는 염을 떼지 않음
    assert resolve_hira_components(["morphine hydrochloride"], _BY_ENG, _MIX) == ({"D000006"}, 2)
    # 단일제는 같은 이름의 '복합' 코드를 빼고 '단일'만
    assert resolve_hira_components(["naproxen"], _BY_ENG, _MIX) == ({"D000195"}, 1)


def test_resolve_hira_components_needs_every_component_and_no_partial_match():
    assert resolve_hira_components(
        ["hydrochlorothiazide", "losartan potassium (as losartan)"], _BY_ENG, _MIX) == ({"D3", "D4"}, 1)
    assert resolve_hira_components(["losartan potassium (as losartan)", "nicotinamide"], _BY_ENG, _MIX) is None
    assert resolve_hira_components(["hydroxy-morphine"], _BY_ENG, _MIX) is None
