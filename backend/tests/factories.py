"""테스트용 최소 시드 데이터 헬퍼. 운영 DB와 무관한, 테스트 안에서만 존재하는 가짜 약품."""
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.models.dur_ingredient_rule import (
    DurIngredientContraindication,
    DurIngredientEffectGroup,
)
from app.models.residual_interaction import ResidualInteraction


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
    ingredients: list[tuple[str, str]] | None = None,
) -> Drug:
    """`ingredients`: [(ingr_code, ingr_kor), ...] → drug_ingredients 행도 함께 생성."""
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

    for code, kor in ingredients or []:
        session.add(DrugIngredient(
            drug_id=drug.id, ingr_code=code, ingr_kor=kor, source="dur",
        ))
    if ingredients:
        await session.commit()
    return drug


async def make_contraindication(
    session: AsyncSession, drug1: Drug, drug2: Drug, mechanism: str = "테스트 병용금기 기전"
) -> ResidualInteraction:
    """잔여 폴백(residual_interactions) 병용금기 쌍. quick_check는 두 약 중 하나라도
    성분코드 미해소일 때만 이걸 본다."""
    row = ResidualInteraction(
        drug1_id=drug1.id, drug2_id=drug2.id,
        interaction_type="contraindicated", mechanism=mechanism,
    )
    session.add(row)
    await session.commit()
    return row


async def make_effect_group(
    session: AsyncSession, drugs: list[Drug], dur_seq: str, effect_name: str = "테스트 효능군"
) -> None:
    """잔여 폴백 효능군중복 — 약품 목록의 모든 쌍을 residual_interactions에 넣는다
    (구 drug_effect_groups 멤버십 대신 쌍 전개된 형태)."""
    for i in range(len(drugs)):
        for j in range(i + 1, len(drugs)):
            session.add(ResidualInteraction(
                drug1_id=drugs[i].id, drug2_id=drugs[j].id,
                interaction_type="duplicate_effect_group",
                mechanism=f"효능군 중복: {effect_name}",
            ))
    await session.commit()


async def make_ingr_contraindication(
    session: AsyncSession, code_a: str, code_b: str,
    kor_a: str = "성분A", kor_b: str = "성분B",
    prohibit_content: str = "테스트 성분 병용금기",
    risk_tags: list[str] | None = None,
) -> DurIngredientContraindication:
    """성분코드 쌍 병용금기 규칙 (정규 순서 a<b로 저장)."""
    if code_a > code_b:
        code_a, code_b = code_b, code_a
        kor_a, kor_b = kor_b, kor_a
    rule = DurIngredientContraindication(
        ingr_code_a=code_a, ingr_code_b=code_b,
        ingr_kor_a=kor_a, ingr_kor_b=kor_b,
        prohibit_content=prohibit_content, risk_tags=risk_tags,
    )
    session.add(rule)
    await session.commit()
    return rule


async def make_ingr_effect_group(
    session: AsyncSession, members: list[tuple[str, str]], dur_seq: str,
    effect_name: str = "테스트 성분 효능군",
) -> None:
    """members: [(ingr_code, ingr_kor), ...] — 같은 dur_seq 효능군 멤버십 (ingr_kor는 무시)."""
    for code, _kor in members:
        session.add(DurIngredientEffectGroup(
            ingr_code=code, dur_seq=dur_seq, effect_name=effect_name,
        ))
    await session.commit()
