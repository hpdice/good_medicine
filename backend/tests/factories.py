"""테스트용 최소 시드 데이터 헬퍼. 운영 DB와 무관한, 테스트 안에서만 존재하는 가짜 약품."""
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.models.dur_ingredient_rule import (
    DurIngredientAgeCaution,
    DurIngredientContraindication,
    DurIngredientDoseCaution,
    DurIngredientEffectGroup,
    DurItemPregnancyTaboo,
)
from app.models.hira import HiraGenCode, HiraGenIngredient, HiraItemGenCode
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


async def register_and_login_with_profile(
    client: AsyncClient,
    health_conditions: list[str] | None = None,
    birth_year: int | None = None,
    email: str | None = None,
    is_pregnant: bool | None = None,
) -> str:
    """register_and_login + PATCH /users/me로 건강 상태·출생연도·임신 여부까지 채운 토큰 반환."""
    token = await register_and_login(client, email=email)
    body = {}
    if health_conditions is not None:
        body["health_conditions"] = health_conditions
    if birth_year is not None:
        body["birth_year"] = birth_year
    if is_pregnant is not None:
        body["is_pregnant"] = is_pregnant
    if body:
        res = await client.patch(
            "/users/me", json=body, headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200, res.text
    return token


async def make_drug(
    session: AsyncSession,
    item_name: str,
    class_name: str | None = None,
    item_seq: str | None = None,
    ingr_name: list[dict] | None = None,
    ingredients: list[tuple[str, str]] | None = None,
    etc_otc_name: str | None = None,
    amounts: dict[str, float] | None = None,
) -> Drug:
    """`ingredients`: [(ingr_code, ingr_kor), ...] → drug_ingredients 행도 함께 생성.
    `etc_otc_name`: "일반의약품" / "전문의약품". `amounts`: {ingr_code: 정·캡슐 1개당 mg}."""
    drug = Drug(
        item_seq=item_seq or f"TEST_{uuid.uuid4().hex[:12]}",
        item_name=item_name,
        simple_name=item_name,
        drug_key=item_name.lower(),
        class_name=class_name,
        ingr_name=ingr_name,
        etc_otc_name=etc_otc_name,
    )
    session.add(drug)
    await session.commit()
    await session.refresh(drug)

    for code, kor in ingredients or []:
        session.add(DrugIngredient(
            drug_id=drug.id, ingr_code=code, ingr_kor=kor, source="dur",
            amount_mg=(amounts or {}).get(code),
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
    effect_name: str = "테스트 성분 효능군", sers_name: str | None = None,
) -> None:
    """members: [(ingr_code, ingr_kor), ...] — 효능군·계열 멤버십 (ingr_kor는 무시).
    실제 데이터처럼 성분마다 다른 dur_seq를 주려면 성분별로 따로 부른다."""
    for code, _kor in members:
        session.add(DurIngredientEffectGroup(
            ingr_code=code, dur_seq=dur_seq, effect_name=effect_name, sers_name=sers_name,
        ))
    await session.commit()


async def make_ingr_age_caution(
    session: AsyncSession, ingr_code: str, rule_type: str,
    ingr_kor: str = "테스트성분", prohibit_content: str | None = "테스트 연령 규칙",
    age_threshold: int | None = None, age_unit: str | None = None,
    age_direction: str | None = None,
) -> DurIngredientAgeCaution:
    """rule_type: age_taboo | elderly_caution."""
    row = DurIngredientAgeCaution(
        ingr_code=ingr_code, ingr_kor=ingr_kor, rule_type=rule_type,
        prohibit_content=prohibit_content,
        age_threshold=age_threshold, age_unit=age_unit, age_direction=age_direction,
    )
    session.add(row)
    await session.commit()
    return row


async def make_pregnancy_taboo(
    session: AsyncSession, drug: Drug, ingr_code: str = "D700000",
    ingr_kor: str = "테스트성분", prohibit_content: str | None = "동물실험에서 기형발생 보고",
    remark: str | None = None,
) -> DurItemPregnancyTaboo:
    """품목(ITEM_SEQ) 단위 임부금기 규칙 — 성분코드 해소(drug_ingredients)와 무관하게 걸린다."""
    row = DurItemPregnancyTaboo(
        item_seq=drug.item_seq, ingr_code=ingr_code, ingr_kor=ingr_kor,
        prohibit_content=prohibit_content, remark=remark,
    )
    session.add(row)
    await session.commit()
    return row


async def make_ingr_dose_caution(
    session: AsyncSession, ingr_code: str, limits_mg: dict[str, float] | None,
    ingr_kor: str = "테스트성분", mix_codes: str = "", form_name: str = "",
    max_qty: str | None = None, prohibit_content: str | None = None,
) -> DurIngredientDoseCaution:
    """용량주의 규칙. `mix_codes`가 비면 단일제(성분 합계) 규칙, 있으면 그 조성의 복합제 규칙."""
    row = DurIngredientDoseCaution(
        ingr_code=ingr_code, ingr_kor=ingr_kor, mix_codes=mix_codes, form_name=form_name,
        max_qty=max_qty or f"{limits_mg}", limits_mg=limits_mg, prohibit_content=prohibit_content,
    )
    session.add(row)
    await session.commit()
    return row


async def make_hira_form(session: AsyncSession, drug: Drug, form_name: str) -> None:
    """약에 심평원 일반명코드·제형을 붙인다(용량주의 규칙의 제형 맞추기용)."""
    gen_code = f"T{uuid.uuid4().hex[:5].upper()}ATB"
    session.add(HiraItemGenCode(item_seq=drug.item_seq, gen_code=gen_code))
    session.add(HiraGenCode(gen_code=gen_code, form_name=form_name))
    await session.flush()  # 성분 행의 외래 키보다 일반명코드가 먼저 저장돼야 한다
    session.add(HiraGenIngredient(gen_code=gen_code, seq=1, ingr_name="test ingredient"))
    await session.commit()
