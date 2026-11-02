"""DUR 용량주의 — 규칙 파싱, 1개당 함량, 약봉투 복용량 읽기, 하루 양 판정."""
from app.services import ollama_client
from app.services.ocr_service import extract_candidates, extract_doses
from app.services.public_data_service.helpers import (
    dose_rules_from_ingredient,
    hira_amount_mg,
    parse_max_qty,
)
from tests.factories import make_drug, make_hira_form, make_ingr_dose_caution, register_and_login

APAP, TRAMADOL = "D000147", "D000773"


# ---------- 규칙·함량 파싱 ----------


def test_parse_max_qty_reads_plain_and_named_limits():
    assert parse_max_qty("4,000밀리그램") == [(None, 4000.0)]
    assert parse_max_qty("트리플루리딘으로 160밀리그램") == [("트리플루리딘", 160.0)]
    assert parse_max_qty("5마이크로그램") == [(None, 0.005)]
    assert parse_max_qty("아세트아미노펜 2,600밀리그램/트라마돌염산염 300밀리그램") == [
        ("아세트아미노펜", 2600.0), ("트라마돌염산염", 300.0),
    ]


def test_parse_max_qty_skips_conditional_limits():
    for text in ("(고령자)멕사졸람 1.5밀리그램", "세마글루티드 주 1회 2.4밀리그램", "360메가베크렐",
                 "디클로페낙나트륨 100밀리그램 또는 디클로페낙칼륨 100밀리그램", "", None):
        assert parse_max_qty(text) is None


def _dose_row(code, name, max_qty, mix="", form="정제", content=None):
    return {"INGR_CODE": code, "INGR_NAME": name, "MIX_INGR": mix, "FORM_NAME": form,
            "MAX_QTY": max_qty, "PROHBT_CONTENT": content, "REMARK": None, "DEL_YN": "정상"}


def test_dose_rules_map_compound_limits_to_codes_by_name():
    rules = dose_rules_from_ingredient([
        _dose_row(APAP, "아세트아미노펜", "아세트아미노펜 4,000밀리그램", form="고형제/반고형제/액제"),
        _dose_row(APAP, "아세트아미노펜", "아세트아미노펜 2,600밀리그램/트라마돌염산염 300밀리그램",
                  mix=f"[{TRAMADOL}]Tramadol(트라마돌)"),
        _dose_row("D000220", "로사르탄", "로사르탄칼륨 100밀리그램/히드로클로로티아지드 25밀리그램",
                  mix="[D000414]Hydrochlorothiazide(히드로클로로티아지드)"),
        _dose_row("D000592", "트리아졸람", "(고령자)트리아졸람 0.125밀리그램"),
        {**_dose_row("D000001", "삭제된성분", "10밀리그램"), "DEL_YN": "삭제"},
    ])
    assert rules[(APAP, "", "고형제/반고형제/액제", "아세트아미노펜 4,000밀리그램")]["limits_mg"] == {APAP: 4000.0}
    combo = rules[(APAP, TRAMADOL, "정제", "아세트아미노펜 2,600밀리그램/트라마돌염산염 300밀리그램")]
    assert combo["limits_mg"] == {APAP: 2600.0, TRAMADOL: 300.0}
    losartan = rules[("D000220", "D000414", "정제", "로사르탄칼륨 100밀리그램/히드로클로로티아지드 25밀리그램")]
    assert losartan["limits_mg"] == {"D000220": 100.0, "D000414": 25.0}  # 염 이름도 성분명으로 시작하면 맞춘다
    assert rules[("D000592", "", "정제", "(고령자)트리아졸람 0.125밀리그램")]["limits_mg"] is None
    assert len(rules) == 4


def test_single_rule_citing_higher_dose_is_conditional():
    """원문에 적응증별로 더 큰 용량이 적힌 단일제 규칙은 사용자의 적응증을 몰라 판정하지 않는다."""
    rules = dose_rules_from_ingredient([_dose_row(
        "D000527", "리바록사반", "리바록사반 20밀리그램",
        content="(비판막성 심방세동) 리바록사반 20mg,  (심재성 정맥혈전증의 치료) 리바록사반 30mg",
    )])
    assert next(iter(rules.values()))["limits_mg"] is None
    plain = dose_rules_from_ingredient([_dose_row(APAP, "아세트아미노펜", "4,000밀리그램",
                                                  content="아세트아미노펜으로서 4,000mg/day(모든제형)")])
    assert next(iter(plain.values()))["limits_mg"] == {APAP: 4000.0}


def test_hira_amount_only_for_tablets_and_capsules_in_mass_units():
    assert hira_amount_mg("0.5", "g", "정제,저작정") == 500.0
    assert hira_amount_mg("45.8", "mg", "연질캡슐제") == 45.8
    assert hira_amount_mg("200", "μg", "서방형정제") == 0.2
    assert hira_amount_mg("300", "mg", "액제") is None  # 개수로 세지 않는 제형
    assert hira_amount_mg("5", "mg", "현탁액제,현탁액용정제,현탁액용산제") is None
    assert hira_amount_mg("1", "mg(1mg/mL)", "정제,저작정") is None
    assert hira_amount_mg("325", "mg/정(야간용)", "정제,저작정") is None


# ---------- 약봉투·처방전 복용량 읽기 ----------

# 실제 약봉투 사진의 OCR 원문(2026-10-19) — '투악량'·'1희'·'종투약일수' 오인식이 섞여 있다
_ENVELOPE = (
    "(임부금기)신플랙스세이프정.. 1희투약량1  1일투여횟수2 총투약일수7\n"
    "노란색 정제                         260        소염진통제\n"
    "ㅣ 뉴부틴서방정(말레인산트리메.. 1회투악량1      1일투여횟수2 _ 종투약일수 7      썩\n"
    "아니스펜8시간이알서방정(아..  1회투약량 1\n"
    "1회투약량1 1일투여횟수2 총투약일수7\n"
)


def test_extract_doses_from_real_envelope_text():
    candidates = extract_candidates(_ENVELOPE)
    doses = extract_doses(_ENVELOPE, candidates)
    expected = {"units_per_intake": 1.0, "times_per_day": 2, "duration_days": 7}
    assert doses["신플랙스세이프정"] == expected
    assert doses["뉴부틴서방정"] == expected
    # 이름 줄에 일부만 있고 나머지는 다음 줄에 있다
    assert doses["아니스펜8시간이알서방정"] == expected


def test_extract_doses_reads_table_and_phrase_but_not_header():
    text = (
        "처방 의약품 명칭      1회 투약량   1일 투여횟수   일수\n"
        "뉴심바드정  1  1  30\n"
        "타이레놀정 1회 2정씩 1일 3회 5일분\n"
    )
    doses = extract_doses(text, extract_candidates(text))
    assert doses["뉴심바드정"] == {"units_per_intake": 1.0, "times_per_day": 1, "duration_days": 30}
    assert doses["타이레놀정"] == {"units_per_intake": 2.0, "times_per_day": 3, "duration_days": 5}
    # 머리글의 '투약량   1일'은 값이 아니다
    assert extract_doses("가스활명수정\n1회 투약량   1일 투여횟수   일수\n", ["가스활명수정"]) == {}


def test_extract_doses_drops_out_of_range_values():
    doses = extract_doses("가스활명수정 1회투약량1 1일투여횟수47 총투약일수7\n", ["가스활명수정"])
    assert doses == {"가스활명수정": {"units_per_intake": 1.0, "duration_days": 7}}


# ---------- 하루 양 판정 ----------


async def _box(client, headers, drug, units=None, times=None):
    body = {"drug_id": str(drug.id)}
    if units is not None:
        body |= {"units_per_intake": units, "times_per_day": times}
    res = await client.post("/medicine-box", json=body, headers=headers)
    assert res.status_code == 201


async def _check(client, headers, *drugs):
    res = await client.post("/analysis/quick-check", json={"drug_ids": [str(d.id) for d in drugs]}, headers=headers)
    assert res.status_code == 200
    return res.json()


async def _headers(client):
    return {"Authorization": f"Bearer {await register_and_login(client)}"}


async def test_same_ingredient_from_two_drugs_is_summed_against_daily_max(client, session_factory):
    """감기약 + 해열제에 든 아세트아미노펜을 합치면 하루 4,000mg을 넘는다 — 각각은 넘지 않는다."""
    async with session_factory() as session:
        cold = await make_drug(session, "테스트감기정", ingredients=[(APAP, "아세트아미노펜")], amounts={APAP: 325})
        tylenol = await make_drug(session, "테스트해열정500", ingredients=[(APAP, "아세트아미노펜")], amounts={APAP: 500})
        await make_ingr_dose_caution(session, APAP, {APAP: 4000.0}, ingr_kor="아세트아미노펜",
                                     form_name="고형제/반고형제/액제", prohibit_content="모든 제형")
    headers = await _headers(client)
    await _box(client, headers, cold, units=2, times=3)  # 1,950mg
    await _box(client, headers, tylenol, units=1, times=5)  # 2,500mg

    body = await _check(client, headers, cold, tylenol)
    assert body["risk_level"] == "caution"
    assert body["dose_caution_count"] == 1
    caution = body["dose_cautions"][0]
    assert caution["ingredient"] == "아세트아미노펜" and caution["scope"] == "total"
    assert caution["daily_mg"] == 4450 and caution["max_daily_mg"] == 4000
    assert set(caution["drug_names"]) == {"테스트감기정", "테스트해열정500"}
    # 같은 성분 두 약이라 동일 성분 중복도 함께 잡힌다(별개 판정)
    assert body["duplicate_ingredient_count"] == 1


async def test_under_daily_max_or_without_dose_is_not_flagged(client, session_factory):
    async with session_factory() as session:
        tylenol = await make_drug(session, "테스트해열정500", ingredients=[(APAP, "아세트아미노펜")], amounts={APAP: 500})
        await make_ingr_dose_caution(session, APAP, {APAP: 4000.0}, ingr_kor="아세트아미노펜")
    headers = await _headers(client)
    await _box(client, headers, tylenol, units=2, times=4)  # 4,000mg — 넘지 않음

    body = await _check(client, headers, tylenol)
    assert body["dose_cautions"] == [] and body["risk_level"] == "safe"

    other = await _headers(client)  # 복용량을 안 적은 사용자
    await _box(client, other, tylenol)
    assert (await _check(client, other, tylenol))["dose_cautions"] == []


async def test_drug_without_dose_is_reported_as_uncounted(client, session_factory):
    async with session_factory() as session:
        tylenol = await make_drug(session, "테스트해열정500", ingredients=[(APAP, "아세트아미노펜")], amounts={APAP: 500})
        cold = await make_drug(session, "테스트감기정", ingredients=[(APAP, "아세트아미노펜")], amounts={APAP: 325})
        await make_ingr_dose_caution(session, APAP, {APAP: 4000.0}, ingr_kor="아세트아미노펜")
    headers = await _headers(client)
    await _box(client, headers, tylenol, units=3, times=3)  # 4,500mg
    await _box(client, headers, cold)  # 복용량 모름

    caution = (await _check(client, headers, tylenol, cold))["dose_cautions"][0]
    assert caution["drug_names"] == ["테스트해열정500"]
    assert caution["uncounted_drug_names"] == ["테스트감기정"]


async def test_compound_rule_applies_to_that_product_only(client, session_factory):
    """아세트아미노펜+트라마돌 복합제 하루 10정: 트라마돌 375mg > 300mg(복합제 기준). 아세트아미노펜 3,250mg은
    단일제 기준(4,000mg) 안이지만 복합제 기준(2,600mg)을 넘는다."""
    async with session_factory() as session:
        combo = await make_drug(session, "테스트세트정", ingredients=[(APAP, "아세트아미노펜"), (TRAMADOL, "트라마돌")],
                                amounts={APAP: 325, TRAMADOL: 37.5})
        await make_hira_form(session, combo, "정제,저작정")
        await make_ingr_dose_caution(session, APAP, {APAP: 4000.0}, ingr_kor="아세트아미노펜")
        await make_ingr_dose_caution(session, APAP, {APAP: 2600.0, TRAMADOL: 300.0}, ingr_kor="아세트아미노펜",
                                     mix_codes=TRAMADOL, form_name="정제/서방성필름코팅정")
        await make_ingr_dose_caution(session, TRAMADOL, {TRAMADOL: 400.0}, ingr_kor="트라마돌")
    headers = await _headers(client)
    await _box(client, headers, combo, units=2, times=5)

    cautions = (await _check(client, headers, combo))["dose_cautions"]
    got = {(c["ingredient"], c["scope"], c["daily_mg"], c["max_daily_mg"]) for c in cautions}
    assert got == {("아세트아미노펜", "product", 3250, 2600), ("트라마돌", "product", 375, 300)}


async def test_rule_applies_only_to_matching_dose_form(client, session_factory):
    """클로미프라민: 정제(조루증용) 기준 15mg은 우울증용 캡슐에 쓰지 않는다. 서방형은 서방형 기준을 쓴다.
    주사제 기준은 정·캡슐에 쓰지 않고, 제형을 모르는 약에는 제형이 정해진 규칙을 쓰지 않는다."""
    code, sr_code, inj_code = "D000277", "D900002", "D900001"
    async with session_factory() as session:
        capsule = await make_drug(session, "테스트캡슐25", ingredients=[(code, "클로미프라민")], amounts={code: 25})
        await make_hira_form(session, capsule, "경질캡슐제")
        tablet = await make_drug(session, "테스트정15", ingredients=[(code, "클로미프라민")], amounts={code: 15})
        await make_hira_form(session, tablet, "정제,저작정")
        await make_ingr_dose_caution(session, code, {code: 15.0}, ingr_kor="클로미프라민", form_name="정제")

        sr = await make_drug(session, "테스트서방정", ingredients=[(sr_code, "다른성분")], amounts={sr_code: 100})
        await make_hira_form(session, sr, "서방형정제")
        await make_ingr_dose_caution(session, sr_code, {sr_code: 150.0}, form_name="정제")
        await make_ingr_dose_caution(session, sr_code, {sr_code: 300.0}, form_name="서방정")

        unknown = await make_drug(session, "테스트주사성분정", ingredients=[(inj_code, "주사성분")], amounts={inj_code: 100})
        await make_ingr_dose_caution(session, inj_code, {inj_code: 150.0}, form_name="정제/용액주사제")
    headers = await _headers(client)
    await _box(client, headers, capsule, units=1, times=1)
    await _box(client, headers, tablet, units=2, times=1)  # 정제만 30mg > 15mg
    await _box(client, headers, sr, units=1, times=2)  # 서방형 200mg < 300mg
    await _box(client, headers, unknown, units=1, times=2)  # 제형 모름

    cautions = (await _check(client, headers, capsule, tablet, sr, unknown))["dose_cautions"]
    assert [(c["drug_names"], c["daily_mg"], c["max_daily_mg"]) for c in cautions] == [(["테스트정15"], 30, 15)]


async def test_dose_fields_round_trip_and_clear(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _headers(client)
    res = await client.post("/medicine-box", json={"drug_id": str(drug.id), "units_per_intake": 0.5,
                                                    "times_per_day": 3}, headers=headers)
    assert (res.json()["units_per_intake"], res.json()["times_per_day"]) == (0.5, 3)
    entry_id = res.json()["id"]

    res = await client.patch(f"/medicine-box/{entry_id}", json={"notes": "식후"}, headers=headers)
    assert res.json()["times_per_day"] == 3  # 다른 필드 수정은 복용량을 건드리지 않는다
    res = await client.patch(f"/medicine-box/{entry_id}", json={"units_per_intake": None, "times_per_day": None},
                             headers=headers)
    assert (res.json()["units_per_intake"], res.json()["times_per_day"]) == (None, None)

    bad = await client.post("/medicine-box", json={"drug_id": str(drug.id), "times_per_day": 0}, headers=headers)
    assert bad.status_code == 422


async def test_guide_explains_dose_caution_with_dose_advice(client, session_factory, monkeypatch):
    prompts = []

    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        prompts.append(prompt)
        return "테스트해열정500은 열을 내리는 약이에요.\n\n식약처가 정한 하루 최대 용량을 넘게 드시고 있어요."

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)
    async with session_factory() as session:
        tylenol = await make_drug(session, "테스트해열정500", ingredients=[(APAP, "아세트아미노펜")], amounts={APAP: 500})
        await make_ingr_dose_caution(session, APAP, {APAP: 4000.0}, ingr_kor="아세트아미노펜")
    headers = await _headers(client)
    await _box(client, headers, tylenol, units=2, times=5)

    res = await client.post("/analysis/guide", json={"drug_ids": [str(tylenol.id)]}, headers=headers)
    body = res.json()
    assert body["risk_level"] == "caution" and body["is_ai_generated"] is True
    assert "[하루 최대 용량 초과]" in prompts[0]
    assert "아세트아미노펜 5,000mg" in prompts[0] and "하루 최대 4,000mg" in prompts[0]
    assert body["guide_text"].endswith("처방받은 양이라면 임의로 줄이거나 끊지는 마세요.")
