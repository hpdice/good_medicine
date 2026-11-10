"""화면용 주의사항 줄이기 — 임상시험 결과 등 사용자에게 필요 없는 항목을 뺀다(DB 원문은 그대로)."""
import re
import uuid
from datetime import datetime, timezone

from app.schemas.drug import DrugSearchResult
from app.services.precautions import trim_precautions_for_display

_DOC = "\n".join([
    "1. 경고",
    "1) 알코올과 함께 복용하지 않는다.",
    "2. 다음 환자에는 투여하지 말 것",
    "1) 이 약의 성분에 과민성이 있는 환자",
    "3. 이상반응",
    "3.1. 임상시험 자료",
    "1) 이 약의 위약 대조 임상시험 중 이 약 투여군에서 1% 이상의 비율로 보고된 이상반응",
    "신체/기관분류 | 이상반응",
    "식욕감퇴 | 불면",
    "3.2. 시판 후 이상반응",
    "구역, 구토",
    "4. 약물상호작용",
    "1) MAO억제제",
    "5. 과량 투여시의 처치",
    "해독제를 투여한다.",
    "6. 기타",
    "동물시험에서 내성이 나타났다.",
    "7. 보관 및 취급상의 주의사항",
    "1) 어린이의 손이 닿지 않는 곳에 보관할 것",
])


def test_drops_clinical_trial_results_and_other_expert_sections():
    out = trim_precautions_for_display(_DOC) or ""
    assert "임상시험" not in out and "위약 대조" not in out and "신체/기관분류" not in out
    assert "과량" not in out and "해독제" not in out and "동물시험" not in out
    # 사용자에게 필요한 항목은 그대로
    for keep in ("알코올과 함께", "과민성이 있는 환자", "구역, 구토", "MAO억제제", "어린이의 손이 닿지 않는 곳"):
        assert keep in out


def test_renumbers_headings_after_dropping():
    lines = (trim_precautions_for_display(_DOC) or "").split("\n")
    assert [ln for ln in lines if re.match(r"^\d+\. ", ln)] == [
        "1. 경고", "2. 다음 환자에는 투여하지 말 것", "3. 이상반응", "4. 약물상호작용", "5. 보관 및 취급상의 주의사항",
    ]
    assert "3.1. 시판 후 이상반응" in lines  # 3.1을 뺐으니 3.2가 3.1이 된다


def test_returns_original_when_nothing_to_drop_or_format_unknown():
    plain = "1. 경고\n알코올 주의\n2. 이상반응\n구역"
    assert trim_precautions_for_display(plain) == plain
    free = "복용 중 졸음이 올 수 있습니다.\n운전에 주의하세요."  # 항목 번호가 없는 e약은요식 글
    assert trim_precautions_for_display(free) == free
    assert trim_precautions_for_display(None) is None and trim_precautions_for_display("") == ""


def test_never_returns_empty_text():
    only_dropped = "1. 과량 투여시의 처치\n해독제를 투여한다."
    assert trim_precautions_for_display(only_dropped) == only_dropped


def test_response_schema_trims_but_source_text_is_untouched():
    class Row:  # ORM 행 흉내 — from_attributes로 읽힌다
        id = uuid.uuid4()
        item_seq = "1"
        item_name = "테라펜정"
        simple_name = "테라펜정"
        entp_name = class_name = etc_otc_name = None
        efcy_qesitm = use_method_qesitm = atpn_warn_qesitm = intrc_qesitm = se_qesitm = deposit_method_qesitm = None
        atpn_qesitm = _DOC
        created_at = datetime.now(timezone.utc)

    res = DrugSearchResult.model_validate(Row())
    assert "임상시험" not in (res.atpn_qesitm or "")
    assert "임상시험" in Row.atpn_qesitm  # 판정·AI 근거로 쓰는 원문은 그대로
