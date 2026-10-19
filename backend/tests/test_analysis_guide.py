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
    assert "임의로 끊거나 바꾸지 말고" in body["guide_text"]
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
    모델이 '두 약의 병용이 critical'처럼 없는 상호작용을 지어냈다(2026-10-15 실측)."""
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
        "두 약을 함께 먹으면 근병증 위험이 커집니다.\n\n약을 임의로 끊거나 바꾸지 말고 처방한 의사나 약사와 상담하세요."
    )


async def test_allergy_guide_closes_with_allergy_advice_not_keep_taking(client, session_factory, monkeypatch):
    """알레르기 성분이 든 약에 '임의로 끊지 말라'가 붙으면 안 된다 — 종류별 대응 문장."""
    prompts = []

    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        prompts.append(prompt)
        return "이 약에는 등록하신 알레르기 성분인 페니실린이 들어 있습니다."

    monkeypatch.setattr(ollama_client.OllamaClient, "generate", fake_generate)

    async with session_factory() as session:
        drug_a = await make_drug(session, "테스트가이드페니실린정", ingredients=[("D500101", "페니실린")])
        drug_b = await make_drug(session, "테스트가이드비타민정")

    token = await register_and_login_with_profile(client, allergy_info=["페니실린"])
    res = await client.post(
        "/analysis/guide",
        json={"drug_ids": [str(drug_a.id), str(drug_b.id)]},
        headers={"Authorization": f"Bearer {token}"},
    )
    text = res.json()["guide_text"]
    assert "알레르기 성분 충돌" in prompts[0] and "페니실린" in prompts[0]
    assert "알레르기가 있다고 알리고" in text
    assert "끊거나 바꾸지 말고" not in text  # 병용 문제가 없으니 병용용 문장은 붙지 않는다


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
        ("근육이 해.TryParse()损坏", "한자·가나 섞임"),
        ("", "빈 응답"),
    ],
)
def test_guide_text_problem(text, problem):
    assert guide_text_problem(text) == problem


async def test_guide_requires_at_least_two_drugs(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    res = await client.post(
        "/analysis/guide", json={"drug_ids": [str(drug.id)]}, headers=headers
    )
    assert res.status_code == 422
