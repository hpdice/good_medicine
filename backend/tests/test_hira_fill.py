"""심평원 경로(build_drug_ingredients_from_hira) — 미해소 약 해소와 일부만 맺힌 약의 빠진 성분 보태기."""
from sqlalchemy import select

from app.models.drug_ingredient import DrugIngredient
from app.models.dur_ingredient_master import DurIngredientMaster
from app.models.hira import HiraGenIngredient, HiraItemGenCode
from app.services.public_data_service import PublicDataService
from tests.factories import make_drug

APAP, GUAI, CAFF, CSA, CSA2 = "D000147", "D000493", "D000200", "D000334", "D001077"


async def _master(session):
    for code, kor, eng in ((APAP, "아세트아미노펜", "acetaminophen"), (GUAI, "구아이페네신", "guaifenesin"),
                           (CAFF, "카페인", "caffeine"), (CSA, "사이클로스포린", "cyclosporine"),
                           (CSA2, "사이클로스포린", "cyclosporine")):
        session.add(DurIngredientMaster(ingr_code=code, ingr_kor=kor, ingr_eng=eng, ingr_eng_norm=eng, mix_type="단일"))
    await session.commit()


async def _hira(session, drug, gen_code, names):
    session.add(HiraItemGenCode(item_seq=drug.item_seq, gen_code=gen_code))
    for seq, name in enumerate(names, 1):
        session.add(HiraGenIngredient(gen_code=gen_code, seq=seq, ingr_name=name, form_name="정제,저작정"))
    await session.commit()


async def _codes(session, drug):
    rows = (await session.execute(
        select(DrugIngredient.ingr_code, DrugIngredient.source).where(DrugIngredient.drug_id == drug.id)
    )).all()
    return sorted(rows)


async def test_hira_resolves_new_drug_and_fills_missing_component(session_factory):
    async with session_factory() as session:
        await _master(session)
        new = await make_drug(session, "새감기정")
        await _hira(session, new, "T00001ATB", ["acetaminophen", "caffeine"])
        partial = await make_drug(session, "부분감기정", ingredients=[(GUAI, "구아이페네신")])
        await _hira(session, partial, "T00002ATB", ["acetaminophen", "guaifenesin"])
        full = await make_drug(session, "다맺힌정", ingredients=[(APAP, "아세트아미노펜")])
        await _hira(session, full, "T00003ATB", ["acetaminophen"])

        changed = await PublicDataService(session).build_drug_ingredients_from_hira()

        assert changed == 2  # 새로 맺은 약 1 + 빠진 성분을 보탠 약 1 (이미 다 맺힌 약은 그대로)
        assert await _codes(session, new) == sorted([(APAP, "hira_eng"), (CAFF, "hira_eng")])
        assert await _codes(session, partial) == sorted([(APAP, "hira_eng"), (GUAI, "dur")])
        assert await _codes(session, full) == [(APAP, "dur")]


async def test_hira_leaves_drug_whose_existing_codes_disagree(session_factory):
    """기존 코드 중 하나라도 심평원 구성에 없으면 두 출처가 어긋난 것이라 보태지 않는다."""
    async with session_factory() as session:
        await _master(session)
        drug = await make_drug(session, "어긋난정", ingredients=[(CAFF, "카페인")])
        await _hira(session, drug, "T00004ATB", ["acetaminophen", "guaifenesin"])

        assert await PublicDataService(session).build_drug_ingredients_from_hira() == 0
        assert await _codes(session, drug) == [(CAFF, "dur")]


async def test_hira_fill_skips_component_with_two_same_name_codes(session_factory):
    """DUR에 같은 이름의 단일 코드가 둘인 성분은 코드가 하나로 정해지지 않아 보탤 때 쓰지 않는다."""
    async with session_factory() as session:
        await _master(session)
        drug = await make_drug(session, "테스트사이클로주", ingredients=[(CSA, "사이클로스포린")])
        await _hira(session, drug, "T00005BIJ", ["cyclosporine"])
        combo = await make_drug(session, "테스트복합정", ingredients=[(GUAI, "구아이페네신")])
        await _hira(session, combo, "T00006ATB", ["guaifenesin", "acetaminophen", "cyclosporine"])

        assert await PublicDataService(session).build_drug_ingredients_from_hira() == 1
        assert await _codes(session, drug) == [(CSA, "dur")]
        # 맞는 코드가 하나인 아세트아미노펜만 보태고, 사이클로스포린 두 코드는 붙이지 않는다
        assert await _codes(session, combo) == sorted([(APAP, "hira_eng"), (GUAI, "dur")])
