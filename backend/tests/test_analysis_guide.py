import pytest
from sqlalchemy import select

from app.core.encryption import get_encryptor
from app.models.analysis_result import AnalysisResult
from app.services import ollama_client
from app.services.ai_guide_service import (
    _clip_field,
    drop_trailing_advice,
    guide_text_problem,
    repair_guide_text,
    sanitize_guide_text,
)
from tests.factories import (
    make_contraindication,
    make_drug,
    make_effect_group,
    make_pregnancy_taboo,
    register_and_login,
    register_and_login_with_profile,
)


async def _auth_headers(client) -> dict:
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}


async def test_guide_generated_for_critical_finding(client, session_factory, monkeypatch):
    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        assert "혈액학적 독성" in prompt  # 실제 finding의 mechanism이 프롬프트에 들어갔는지
        return "테스트용 AI 설명입니다."

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)

    async with session_factory() as session:
        drug_a = await make_drug(session, "경동아스피린장용정", class_name="해열.진통.소염제")
        drug_b = await make_drug(session, "유한메토트렉세이트정", class_name="항악성종양제")
        await make_contraindication(session, drug_a, drug_b, mechanism="혈액학적 독성")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/guide",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "critical"
    # AI 설명 뒤에 판정 종류별 대응 문장(병용금기)이 코드로 붙는다
    assert body["guide_text"].startswith("테스트용 AI 설명입니다.\n\n")
    assert "함께 쓰고 있다고 알리고 확인해 보세요" in body["guide_text"]
    assert "처방한" not in body["guide_text"]  # 처방자를 탓하는 말로 읽히고 일반약에는 맞지 않는다
    assert body["is_ai_generated"] is True
    assert "의사" in body["disclaimer"] or "약사" in body["disclaimer"]

    # 암호화 저장 확인 — 응답 평문과 DB의 복호화 결과가 일치해야 함
    async with session_factory() as session:
        row = (await session.execute(select(AnalysisResult))).scalar_one()
        assert row.risk_level == "critical"
        assert get_encryptor().decrypt(row.action_guide_encrypted) == body["guide_text"]
        # 어떤 약 조합·판정 내역도 암호화 저장 (평문 JSONB 컬럼 없음)
        assert not hasattr(row, "drug_ids")
        assert get_encryptor().decrypt(row.drug_ids_encrypted) == [
            str(drug_a.id), str(drug_b.id),
        ]
        assert isinstance(get_encryptor().decrypt(row.findings_snapshot_encrypted), list)


async def test_guide_for_no_findings_skips_model_and_states_dur_limit(client, session_factory, monkeypatch):
    """확인된 문제가 없을 땐 모델을 부르지 않는다 — 프롬프트에 약 정보가 없어 4개 약을 '두 약'이라 하고
    '안전하다고 판단되었습니다'라고 말했다. 정해진 문장이 실제 약 개수와 DUR 한계를 말해야 한다."""

    async def must_not_call(self, prompt: str, system: str | None = None) -> str:
        raise AssertionError("확인된 문제가 없는데 모델을 불렀다")

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", must_not_call)

    async with session_factory() as session:
        drugs = [await make_drug(session, f"무관한약{i}정") for i in range(4)]

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/guide", json={"drug_ids": [str(d.id) for d in drugs]}, headers=headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "safe"
    assert body["is_ai_generated"] is False
    assert "4개" in body["guide_text"]  # '두 약'이 아니라 실제 개수
    assert "모든 상호작용이 없다는 뜻은 아닙니다" in body["guide_text"]
    assert "안전하다" not in body["guide_text"]


def test_clip_field_cuts_at_line_boundary_not_mid_sentence():
    line = "가" * 100
    text = "\n".join(f"{i}) {line}" for i in range(20))  # 한 줄 ~103자, 총 2000자 이상
    clipped = _clip_field(text)
    assert len(clipped) <= 800
    assert clipped.endswith(line)  # 항목 줄을 통째로 담고 끝난다 — 중간에서 끊기지 않음
    assert _clip_field("짧은 글") == "짧은 글"


async def test_guide_falls_back_safely_when_ollama_unavailable(client, session_factory, monkeypatch):
    async def fake_generate_fail(self, prompt: str, system: str | None = None) -> str:
        raise ollama_client.OllamaUnavailableError("테스트: Ollama 다운")

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate_fail)

    async with session_factory() as session:
        drug_a = await make_drug(session, "크레스토정20밀리그램", class_name="동맥경화용제")
        drug_b = await make_drug(session, "크레스토정10밀리그램", class_name="동맥경화용제")
        await make_effect_group(session, [drug_a, drug_b], dur_seq="9001", effect_name="지질저하제")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/guide",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers=headers,
    )
    # Ollama가 죽어도 판정(caution) 자체는 그대로 살아있고, 요청은 실패하지 않아야 한다
    assert res.status_code == 200
    body = res.json()
    assert body["risk_level"] == "caution"
    assert body["guide_text"]  # 폴백 문구라도 비어있지 않음
    assert body["is_ai_generated"] is False  # 폴백 문구는 AI가 생성한 게 아님을 명시


async def test_guide_prompt_includes_pregnancy_caution_without_risk_code(client, session_factory, monkeypatch):
    """병용 문제 없이 임부금기만 걸려도 그 근거가 프롬프트에 들어가야 한다 — 빠져 있으면
    모델이 '두 약의 병용이 critical'처럼 없는 상호작용을 지어낼 수 있다."""
    prompts = []

    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        prompts.append(prompt)
        return "임신 중에는 이 약을 피해야 합니다. 임의로 복용을 중단하지 말고 의사와 상담하세요."

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)

    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트가이드임부금기정")
        drug_b = await make_drug(session, "테스트가이드동반정")
        await make_pregnancy_taboo(session, drug_a, prohibit_content="1등급 태아독성 보고", remark="경구")

    token = await register_and_login_with_profile(client, is_pregnant=True)
    res = await client.post(
        "/analysis/guide",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["risk_level"] == "critical"
    assert "임신 중이라는 사실을 의사나 약사에게 알리고" in res.json()["guide_text"]
    prompt = prompts[0]
    assert "임부금기" in prompt and "1등급 태아독성 보고" in prompt and "경구" in prompt
    assert "전체 위험도: 위험" in prompt
    assert "critical" not in prompt


async def test_guide_prompt_includes_glossary_only_for_known_terms(client, session_factory, monkeypatch):
    """출처 있는 풀이가 있는 용어만 [용어 풀이]로 넘긴다 — 없는 용어는 모델이 풀이하게 두지 않는다."""
    prompts = []

    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        prompts.append(prompt)
        return "두 약을 함께 먹으면 위험이 커집니다."

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)

    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트가이드용어A정")
        drug_b = await make_drug(session, "테스트가이드용어B정")
        drug_c = await make_drug(session, "테스트가이드용어C정")
        drug_d = await make_drug(session, "테스트가이드용어D정")
        await make_contraindication(session, drug_a, drug_b, mechanism="근병증, 횡문근융해의 위험증가")
        await make_contraindication(session, drug_c, drug_d, mechanism="출혈위험 증가")

    headers = await _auth_headers(client)
    for pair in ((drug_a, drug_b), (drug_c, drug_d)):
        res = await client.post(
            "/analysis/guide", json={"drug_ids": [str(pair[0].id), str(pair[1].id)]}, headers=headers
        )
        assert res.status_code == 200

    assert "[용어 풀이]" in prompts[0] and "횡문근융해증" in prompts[0] and "급성 신부전" in prompts[0]
    assert "[용어 풀이]" not in prompts[1]


def test_system_prompt_keeps_grounding_and_bans_alternatives():
    from app.services.ai_guide_service import _SYSTEM_PROMPT

    assert "[용어 풀이]" in _SYSTEM_PROMPT  # 풀이 근거를 쓰라는 지시
    assert "대체 약" in _SYSTEM_PROMPT and "복용 시간 조절" in _SYSTEM_PROMPT  # 위험한 제안은 명시 금지
    assert "지어내지" in _SYSTEM_PROMPT  # 근거 밖 내용 금지는 유지
    # 대상(일반 시민)과 해요체 말투 예시가 빠지면 말투가 합니다체로 돌아간다
    assert "일반 시민" in _SYSTEM_PROMPT and "식약처가 정한 기준으로는" in _SYSTEM_PROMPT


async def test_guide_regenerates_once_then_falls_back(client, session_factory, monkeypatch):
    calls = []

    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        calls.append(prompt)
        return "你的回答与提供的信息不符。"  # 살릴 한국어 문장이 하나도 없음

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)

    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트가이드재시도A정")
        drug_b = await make_drug(session, "테스트가이드재시도B정")
        await make_contraindication(session, drug_a, drug_b, mechanism="근병증 위험증가")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/guide", json={"drug_ids": [str(drug_a.id), str(drug_b.id)]}, headers=headers
    )
    body = res.json()
    assert len(calls) == 2  # 한 번만 다시 생성
    assert body["is_ai_generated"] is False
    assert "你" not in body["guide_text"]
    assert body["risk_level"] == "critical"  # 판정은 그대로


async def test_guide_uses_second_attempt_when_first_is_rejected(client, session_factory, monkeypatch):
    answers = iter([
        "**위험**: 지금 바로 복용을 중단하세요.",
        "**두 약을 함께 먹으면** 근병증 위험이 커집니다. 임의로 복용을 중단하지 말고 의사와 상담하세요.",
    ])

    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        return next(answers)

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)

    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트가이드복구A정")
        drug_b = await make_drug(session, "테스트가이드복구B정")
        await make_contraindication(session, drug_a, drug_b, mechanism="근병증 위험증가")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/guide", json={"drug_ids": [str(drug_a.id), str(drug_b.id)]}, headers=headers
    )
    body = res.json()
    assert body["is_ai_generated"] is True
    # AI가 끝에 쓴 상담 문장은 떼고, 종류별 대응 문장을 붙인다
    assert body["guide_text"] == (
        "두 약을 함께 먹으면 근병증 위험이 커집니다.\n\n"
        "의사나 약사에게 이 두 약을 함께 쓰고 있다고 알리고 확인해 보세요. 이미 드시는 중이라면 임의로 끊거나 바꾸지는 마세요."
    )


async def _combination_guide_text(client, session_factory, monkeypatch, otc_a: str, otc_b: str, tag: str) -> str:
    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        return "두 약을 함께 먹으면 근병증 위험이 커집니다."

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)

    async with session_factory() as session:
        drug_a = await make_drug(session, f"테스트가이드{tag}A정", etc_otc_name=otc_a)
        drug_b = await make_drug(session, f"테스트가이드{tag}B정", etc_otc_name=otc_b)
        await make_contraindication(session, drug_a, drug_b, mechanism="근병증 위험증가")

    headers = await _auth_headers(client)
    res = await client.post(
        "/analysis/guide", json={"drug_ids": [str(drug_a.id), str(drug_b.id)]}, headers=headers
    )
    assert res.status_code == 200
    return res.json()["guide_text"]


async def test_combination_guide_with_otc_drug_explains_unprescribed_gap(client, session_factory, monkeypatch):
    """처방 때 DUR 점검은 의사·약사가 이미 받는다 — 일반의약품이 낀 조합은 '처방 점검에 안 잡히는 약'을 더하는
    상황이므로 그에 맞게 말하고, 처방자를 지목하지 않는다."""
    text = await _combination_guide_text(client, session_factory, monkeypatch, "전문의약품", "일반의약품", "OTC")
    assert "처방 없이 산 약은 처방 점검에 잡히지 않을 수 있어요" in text
    assert "함께 드시기 전에" in text and "임의로 끊거나 바꾸지는 마세요" in text
    assert "처방한" not in text


async def test_combination_guide_with_prescription_drugs_only_keeps_default_closing(client, session_factory, monkeypatch):
    text = await _combination_guide_text(client, session_factory, monkeypatch, "전문의약품", "전문의약품", "RX")
    assert "함께 쓰고 있다고 알리고 확인해 보세요" in text
    assert "처방 없이 산 약" not in text


async def test_condition_guide_closes_with_condition_advice_not_keep_taking(client, session_factory, monkeypatch):
    """건강 상태 금기 약에 '임의로 끊지 말라'가 붙으면 안 된다 — 종류별 대응 문장."""
    prompts = []

    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        prompts.append(prompt)
        return "이 약은 지금 건강 상태에서는 먹지 않도록 적혀 있습니다."

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)

    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트가이드금기정")
        drug_a.atpn_qesitm = "1. 다음 환자에는 투여하지 말 것.\n1) 중증의 고혈압 환자\n2. 이상반응\n1) 두통"
        await session.commit()
        drug_b = await make_drug(session, "테스트가이드비타민정")

    token = await register_and_login_with_profile(client, health_conditions=["고혈압"])
    res = await client.post(
        "/analysis/guide",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    text = res.json()["guide_text"]
    assert "건강 상태 금기" in prompts[0] and "고혈압" in prompts[0] and "중증의 고혈압 환자" in prompts[0]
    assert "지금 건강 상태를 알리고" in text
    assert "함께 쓰고 있다고" not in text  # 병용 문제가 없으니 병용용 문장은 붙지 않는다


@pytest.mark.parametrize(
    ("raw", "kept", "removed"),
    [
        # 한자가 나오면 그 문장부터 끝까지 버린다
        ("근육 손상 위험이 있습니다. 함께服用可能会增加风险。 두 약을 같이 먹지 마세요.", "근육 손상 위험이 있습니다.", ["한자·가나 섞임"]),
        # 알레르기·임부금기에서 자주 나오는 중단 권유는 그 문장만 뺀다
        ("이 약에는 알레르기 성분이 있습니다. 즉시 복용을 중단하세요.", "이 약에는 알레르기 성분이 있습니다.", ["복용 중단 권유"]),
        ("위험 등급이 critical입니다. 근병증 위험이 커집니다.", "근병증 위험이 커집니다.", ["내부 등급 코드 노출"]),
        ("근병증 위험이 커집니다.\n\n임의로 복용을 중단하지 말고 의사와 상담하세요.", "근병증 위험이 커집니다.", []),
        ("你的回答与提供的信息不符。", "", ["한자·가나 섞임"]),
        # 약 소개와 위험 설명은 남기고 대체 약 제안 문장만 뺀다
        (
            "뉴심바드정은 콜레스테롤을 낮추는 약입니다. 다른 약물로 교체할 수 있습니다. 근병증 위험이 커집니다.",
            "뉴심바드정은 콜레스테롤을 낮추는 약입니다. 근병증 위험이 커집니다.",
            ["대체 약·치료법 제안"],
        ),
    ],
)
def test_repair_guide_text(raw, kept, removed):
    assert repair_guide_text(raw) == (kept, removed)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("근병증 위험이 커집니다. 의사나 약사와 상담하세요.", "근병증 위험이 커집니다."),
        ("위험이 커집니다.\n\n만약 같이 먹고 있다면 의사와 상담하세요. 약사와도 상담하세요.", "위험이 커집니다."),
        ("상담이 필요한 조합입니다. 근육 손상 위험이 있습니다.", "상담이 필요한 조합입니다. 근육 손상 위험이 있습니다."),
        ("의사나 약사와 상담하세요.", "의사나 약사와 상담하세요."),  # 다 떼면 빈 글이 되니 그대로 둔다
    ],
)
def test_drop_trailing_advice(text, expected):
    assert drop_trailing_advice(text) == expected


def test_sanitize_strips_markdown_but_keeps_text():
    raw = "**대응 방법:**\n- 즉시 상담하세요.\n1. 함께 먹지 마세요.\n## 요약"
    assert sanitize_guide_text(raw) == "대응 방법:\n즉시 상담하세요.\n함께 먹지 마세요.\n요약"


def test_sanitize_fixes_haeyo_typo():
    assert sanitize_guide_text("항생물질이예요. 쓰는 약이예요. 맞는 거예요.") == "항생물질이에요. 쓰는 약이에요. 맞는 거예요."


def test_sanitize_fixes_allergy_typo_only_where_missing():
    assert sanitize_guide_text("알레르 반응과 알레르기 성분") == "알레르기 반응과 알레르기 성분"


def test_sanitize_drops_second_person_address():
    assert sanitize_guide_text("하지만 당신이 심바스타틴에 알레르기가 있어 위험합니다.") == (
        "하지만 심바스타틴에 알레르기가 있어 위험합니다."
    )


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("근병증 위험이 커집니다. 의사와 상담하세요.", None),
        ("임의로 복용을 중단하거나 바꾸지 말고 의사와 상담하세요.", None),
        ("현재 복용 중이라면 즉시 복용을 중단하고 의사에게 알리세요.", "복용 중단 권유"),
        ("위험 등급이 critical인 만큼 주의하세요.", "내부 등급 코드 노출"),
        # 금기 조합에 시간차 복용·대체를 권하는 문장은 막는다
        ("다른 시간에 복용하거나 적절한 대안 치료 방법을 찾는 것이 필요합니다.", "대체 약·치료법 제안"),
        ("위험을 피하려면 다른 약물로 교체할 수 있습니다.", "대체 약·치료법 제안"),
        ("전문가와 상담하여 안전하고 적절한 치료 방법을 찾는 것이 중요합니다.", "대체 약·치료법 제안"),
        ("안전하게 치료를 받기 위한 다른 방법에 대해 조언을 구해야 합니다.", "대체 약·치료법 제안"),
        ("자렐토의 효과가 강해져 출혈 위험이 커진다는 연구 결과가 있습니다.", "근거 없는 연구 인용"),
        # 일반 언급은 막지 않는다
        ("함께 복용 중인 다른 약이 있으면 의사나 약사에게 알려 주세요.", None),
        # 용어집에 없는 용어를 모델이 제 지식으로 풀면 막고, 용어집에 있는 용어의 풀이는 허용한다
        ("'위장관계 이상반응'은 위나 소화기 부분에서 불편함이 생긴다는 뜻이에요.", "출처 없는 용어 풀이"),
        ("'위장관계 이상반응'은 위나 소장에서 문제가 생길 수 있다는 의미예요.", "출처 없는 용어 풀이"),  # "의미예요"도 잡는다
        ("횡문근융해는 근육이 심하게 손상돼 독성 물질이 혈액으로 들어간다는 뜻이에요.", None),
        ("케토라신정은 통증과 염증을 줄이는 약이에요.", None),
        ("근육이 해.TryParse()损坏", "한자·가나 섞임"),
        ("", "빈 응답"),
    ],
)
def test_guide_text_problem(text, problem):
    assert guide_text_problem(text) == problem

