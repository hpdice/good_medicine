import pytest
from sqlalchemy import select

from app.core.encryption import get_encryptor
from app.models.analysis_result import AnalysisResult
from app.services import ollama_client
from app.services.ai_guide_service import guide_text_problem, sanitize_guide_text
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
    assert body["guide_text"] == "테스트용 AI 설명입니다."
    assert body["is_ai_generated"] is True
    assert "의사" in body["disclaimer"] or "약사" in body["disclaimer"]

    # 암호화 저장 확인 — 응답 평문과 DB의 복호화 결과가 일치해야 함
    async with session_factory() as session:
        row = (await session.execute(select(AnalysisResult))).scalar_one()
        assert row.risk_level == "critical"
        assert get_encryptor().decrypt(row.action_guide_encrypted) == "테스트용 AI 설명입니다."
        # 어떤 약 조합·판정 내역도 암호화 저장 (평문 JSONB 컬럼 없음)
        assert not hasattr(row, "drug_ids")
        assert get_encryptor().decrypt(row.drug_ids_encrypted) == [
            str(drug_a.id), str(drug_b.id),
        ]
        assert isinstance(get_encryptor().decrypt(row.findings_snapshot_encrypted), list)


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
    prompt = prompts[0]
    assert "임부금기" in prompt and "1등급 태아독성 보고" in prompt and "경구" in prompt
    assert "전체 위험도: 위험" in prompt
    assert "critical" not in prompt


async def test_guide_regenerates_once_then_falls_back(client, session_factory, monkeypatch):
    calls = []

    async def fake_generate(self, prompt: str, system: str | None = None) -> str:
        calls.append(prompt)
        return "근육 손상 위험이 있습니다. 你的回答与提供的信息不符。"

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
    assert body["guide_text"] == "두 약을 함께 먹으면 근병증 위험이 커집니다. 임의로 복용을 중단하지 말고 의사와 상담하세요."


def test_sanitize_strips_markdown_but_keeps_text():
    raw = "**대응 방법:**\n- 즉시 상담하세요.\n1. 함께 먹지 마세요.\n## 요약"
    assert sanitize_guide_text(raw) == "대응 방법:\n즉시 상담하세요.\n함께 먹지 마세요.\n요약"


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
