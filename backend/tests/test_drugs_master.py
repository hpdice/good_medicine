"""drugs_master — 약 1행으로 모은 통합 데이터셋(build_drugs_master). 원천은 그대로 두고 조인만 한다."""
from datetime import date

from sqlalchemy import select

from app.models.drug_master import DrugMaster
from app.models.hira import HiraGenIngredient, HiraItemGenCode
from app.services.public_data_service import PublicDataService
from tests.factories import make_drug


async def _hira(session, drug, gen_code, components, *, atc=None, cancelled_on=None):
    session.add(HiraItemGenCode(item_seq=drug.item_seq, gen_code=gen_code, atc_code=atc, cancelled_on=cancelled_on))
    for seq, (name, strength, unit) in enumerate(components, 1):
        session.add(HiraGenIngredient(
            gen_code=gen_code, seq=seq, ingr_name=name, form_name="정제,저작정", route="내복",
            strength=strength, unit=unit,
        ))
    await session.commit()


async def _rows(session_factory):
    async with session_factory() as session:
        return {r.item_name: r for r in (await session.execute(select(DrugMaster))).scalars()}


async def test_master_joins_names_hira_and_dur_into_one_row(session_factory):
    async with session_factory() as session:
        drug = await make_drug(
            session, "타이레놀정", class_name="해열.진통.소염제", etc_otc_name="일반의약품",
            ingredients=[("D000147", "아세트아미노펜")], amounts={"D000147": 500.0},
        )
        drug.efcy_qesitm = "열을 내리고 통증을 줄입니다"
        await session.commit()
        await _hira(session, drug, "T00001ATB", [("acetaminophen", "500", "mg")], atc="N02BE01")
        assert await PublicDataService(session).build_drugs_master() == 1

    row = (await _rows(session_factory))["타이레놀정"]
    assert (row.class_name, row.etc_otc_name, row.atc_code) == ("해열.진통.소염제", "일반의약품", "N02BE01")
    assert row.ingredient_status == "dur_resolved" and row.judgeable is True
    assert row.dur_ingr_codes == ["D000147"]
    assert row.dur_ingredients == [{"code": "D000147", "kor": "아세트아미노펜", "source": "dur", "amount_mg": 500.0}]
    assert row.hira_components[0]["eng"] == "acetaminophen" and row.hira_components[0]["strength"] == "500"
    assert row.hira_components[0]["unit"] == "mg" and row.hira_components[0]["route"] == "내복"
    assert row.dosage_form == "정제,저작정" and row.route == "내복"
    assert row.has_efficacy is True and row.has_use_method is False


async def test_master_separates_hira_only_from_no_information(session_factory):
    """"문제 없음"과 "판정할 데이터가 없음"을 데이터로 구분한다 — DUR 코드가 없으면 판정 불가."""
    async with session_factory() as session:
        hira_only = await make_drug(session, "성분만아는약")
        await _hira(session, hira_only, "T00002ATB", [("some ingredient", "10", "mg")])
        await make_drug(session, "정보없는약")
        await PublicDataService(session).build_drugs_master()

    rows = await _rows(session_factory)
    assert rows["성분만아는약"].ingredient_status == "hira_only" and rows["성분만아는약"].judgeable is False
    assert rows["성분만아는약"].dur_ingr_codes == []
    assert rows["정보없는약"].ingredient_status == "none" and rows["정보없는약"].judgeable is False
    assert rows["정보없는약"].hira_components == [] and rows["정보없는약"].atc_code is None


async def test_master_ignores_cancelled_hira_items(session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "취소된품목")
        await _hira(session, drug, "T00003ATB", [("old ingredient", "5", "mg")], atc="X99", cancelled_on=date(2020, 1, 1))
        await PublicDataService(session).build_drugs_master()

    row = (await _rows(session_factory))["취소된품목"]
    assert row.hira_components == [] and row.atc_code is None and row.ingredient_status == "none"


async def test_master_is_rebuilt_from_scratch_each_time(session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "다시만들기")
        svc = PublicDataService(session)
        assert await svc.build_drugs_master() == 1
        await _hira(session, drug, "T00004ATB", [("later added", "1", "g")])
        assert await svc.build_drugs_master() == 1  # 중복 없이 같은 행 수

    row = (await _rows(session_factory))["다시만들기"]
    assert row.ingredient_status == "hira_only"


async def test_refresh_single_row_matches_full_build_and_creates_missing_row(session_factory):
    """한 약의 행만 다시 만들어도 전체 구축과 같은 값이고, 행이 없으면 만든다."""
    from app.services.public_data_service.maintenance import refresh_drugs_master_row

    async with session_factory() as session:
        drug = await make_drug(session, "한행갱신", ingredients=[("D000147", "아세트아미노펜")])
        await _hira(session, drug, "T00005ATB", [("acetaminophen", "500", "mg")], atc="N02BE01")
        await refresh_drugs_master_row(session, drug.id)  # 아직 구축 전 — 행이 없으면 만든다
        one = (await session.execute(select(DrugMaster).where(DrugMaster.drug_id == drug.id))).scalar_one()
        one_values = (one.ingredient_status, one.dur_ingr_codes, one.atc_code, one.hira_components)
        await PublicDataService(session).build_drugs_master()

    row = (await _rows(session_factory))["한행갱신"]
    assert (row.ingredient_status, row.dur_ingr_codes, row.atc_code, row.hira_components) == one_values
