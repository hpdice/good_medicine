from sqlalchemy import select

from app.core.encryption import get_encryptor
from app.models.analysis_result import AnalysisResult
from app.services import ollama_client
from tests.factories import make_contraindication, make_drug, make_effect_group, register_and_login


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


async def test_guide_requires_at_least_two_drugs(client, session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "가스활명수정")
    headers = await _auth_headers(client)

    res = await client.post(
        "/analysis/guide", json={"drug_ids": [str(drug.id)]}, headers=headers
    )
    assert res.status_code == 422
