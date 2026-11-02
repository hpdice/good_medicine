"""DUR 성분정보 → 조회표·판정 규칙 변환 (순수 함수)."""
from app.services.public_data_service.helpers import (
    age_rules_from_ingredient,
    contraindication_rules_from_ingredient,
    effect_groups_from_ingredient,
    ingredient_master_from_rows,
    norm_ingr_eng,
    parse_age_base,
)


def test_eng_name_norm_keeps_salt():
    assert norm_ingr_eng("  Morphine   Sulfate ") == "morphine sulfate"  # 염은 남긴다
    assert norm_ingr_eng("ＡＢＣ") == "abc"
    assert norm_ingr_eng("") is None


def test_parse_age_base_reads_whole_value_only():
    assert parse_age_base("18세 미만") == (18, "세", "미만")
    assert parse_age_base("4주 미만") == (4, "주", "미만")
    assert parse_age_base("24개월 미만") == (24, "개월", "미만")
    assert parse_age_base("65세 이상") == (65, "세", "이상")
    assert parse_age_base("소아") == (None, None, None)
    assert parse_age_base("4주 이상 투여하지 말 것") == (None, None, None)
    assert parse_age_base(None) == (None, None, None)


def _contra(a, b, date, content, remark=None, del_yn="정상"):
    return {"INGR_CODE": a, "INGR_KOR_NAME": f"{a}명", "MIXTURE_INGR_CODE": b, "MIXTURE_INGR_KOR_NAME": f"{b}명",
            "NOTIFICATION_DATE": date, "PROHBT_CONTENT": content, "REMARK": remark, "DEL_YN": del_yn}


def test_contraindication_rules_use_latest_notice_and_normalize_order():
    rules = contraindication_rules_from_ingredient([
        _contra("D2", "D1", "20090303", "근육병증\n"),
        _contra("D1", "D2", "20231220", "근질환 위험 증가"),
        _contra("D1", "D2", "20231220", "근질환 위험 증가"),
        _contra("D1", "D2", "20231220", "횡문근융해 위험", remark="48시간 이내 병용금기"),
    ])
    assert list(rules) == [("D1", "D2")]
    assert rules[("D1", "D2")] == {
        "ingr_kor_a": "D1명", "ingr_kor_b": "D2명",
        "prohibit_content": "근질환 위험 증가\n횡문근융해 위험",
        "remark": "48시간 이내 병용금기",
    }


def test_contraindication_rules_skip_deleted_and_self_pairs():
    rules = contraindication_rules_from_ingredient([
        _contra("D1", "D3", "20200101", "삭제된 규칙", del_yn="삭제"),
        _contra("D4", "D4", "20200101", "자기 자신"),
    ])
    assert rules == {}


def test_effect_groups_keep_effect_and_series():
    groups = effect_groups_from_ingredient([
        {"INGR_CODE": "D000739", "DUR_SEQ": "2463", "EFFECT_CODE": "해열진통소염제",
         "SERS_NAME": "비스테로이드성 소염제", "DEL_YN": "정상"},
        {"INGR_CODE": "D000740", "DUR_SEQ": "2464", "EFFECT_CODE": "해열진통소염제", "DEL_YN": "삭제"},
    ])
    assert groups == {("D000739", "2463"): {"effect_name": "해열진통소염제", "sers_name": "비스테로이드성 소염제"}}


def _age(code, base, content, form="정제"):
    return {"INGR_CODE": code, "INGR_NAME": "성분", "AGE_BASE": base, "PROHBT_CONTENT": content,
            "FORM_NAME": form, "DEL_YN": "정상"}


def test_age_rules_fill_threshold_only_when_age_base_is_single():
    rules = age_rules_from_ingredient([
        _age("D1", "12세 이하", "대사 차이"), _age("D1", "12세 이하", "대사 차이", form="캡슐"),
        _age("D2", "4주 미만", "벤질알코올", form="주사제"), _age("D2", "18세 미만", "안전성 미확립"),
    ], with_age_base=True)
    assert (rules["D1"]["age_threshold"], rules["D1"]["age_unit"], rules["D1"]["age_direction"]) == (12, "세", "이하")
    assert rules["D1"]["prohibit_content"] == "대사 차이"
    # 제형마다 기준이 다르면 약의 제형을 모르므로 채우지 않는다 (문구는 합쳐 남김)
    assert rules["D2"]["age_threshold"] is None
    assert rules["D2"]["prohibit_content"] == "벤질알코올\n안전성 미확립"


def test_elderly_rules_have_no_age_threshold():
    rules = age_rules_from_ingredient([_age("D9", None, "낙상 위험")], with_age_base=False)
    assert rules["D9"]["age_threshold"] is None
    assert rules["D9"]["prohibit_content"] == "낙상 위험"


def test_master_takes_both_sides_of_contraindication():
    names = ingredient_master_from_rows({
        "병용금기": [{
            "MIX_TYPE": "단일", "INGR_CODE": "D000762", "INGR_KOR_NAME": "이트라코나졸", "INGR_ENG_NAME": "Itraconazole",
            "MIXTURE_MIX_TYPE": "복합", "MIXTURE_INGR_CODE": "D000027", "MIXTURE_INGR_KOR_NAME": "심바스타틴",
            "MIXTURE_INGR_ENG_NAME": "Simvastatin",
        }],
        # 다른 오퍼레이션은 INGR_NAME을 쓴다
        "임부금기": [{"MIX_TYPE": "단일", "INGR_CODE": "D000762", "INGR_NAME": "이트라코나졸", "INGR_ENG_NAME": "Itraconazole"}],
    })
    assert names == {("D000762", "이트라코나졸", "Itraconazole"): "단일", ("D000027", "심바스타틴", "Simvastatin"): "복합"}
