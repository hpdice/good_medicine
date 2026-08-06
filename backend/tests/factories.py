"""테스트용 최소 시드 데이터 헬퍼. 운영 DB와 무관한, 테스트 안에서만 존재하는 가짜 약품."""
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drug import Drug
from app.models.drug_effect_group import DrugEffectGroup
from app.models.drug_interaction import DrugInteraction


async def register_and_login(client: AsyncClient, email: str | None = None) -> str:
    """회원가입 + 로그인 후 access_token을 반환한다."""
    email = email or f"user_{uuid.uuid4().hex[:10]}@example.com"
    payload = {
        "email": email,
        "password": "testpass123",
        "name": "테스트유저",
        "privacy_consent": True,
        "health_data_consent": True,
    }
    res = await client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text

    login_res = await client.post(
        "/auth/login", json={"email": email, "password": payload["password"]}
    )
    assert login_res.status_code == 200, login_res.text
    return login_res.json()["access_token"]


async def make_drug(
    session: AsyncSession,
    item_name: str,
    class_name: str | None = None,
    item_seq: str | None = None,
    ingr_name: list[dict] | None = None,
) -> Drug:
    drug = Drug(
        item_seq=item_seq or f"TEST_{uuid.uuid4().hex[:12]}",
        item_name=item_name,
        simple_name=item_name,
        drug_key=item_name.lower(),
        class_name=class_name,
        ingr_name=ingr_name,
    )
    session.add(drug)
    await session.commit()
    await session.refresh(drug)
    return drug


async def make_contraindication(
    session: AsyncSession, drug1: Drug, drug2: Drug, mechanism: str = "테스트 병용금기 기전"
) -> DrugInteraction:
    interaction = DrugInteraction(
        drug1_id=drug1.id, drug2_id=drug2.id,
        interaction_type="contraindicated", mechanism=mechanism,
    )
    session.add(interaction)
    await session.commit()
    return interaction


async def make_effect_group(
    session: AsyncSession, drugs: list[Drug], dur_seq: str, effect_name: str = "테스트 효능군"
) -> None:
    for drug in drugs:
        session.add(DrugEffectGroup(drug_id=drug.id, dur_seq=dur_seq, effect_name=effect_name))
    await session.commit()
