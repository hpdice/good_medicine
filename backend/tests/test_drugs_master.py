"""drugs_master — 약 1행으로 모은 통합 데이터셋(뷰). 저장된 사본이 아니라 원천을 읽을 때마다 조인한다."""
from datetime import date

from sqlalchemy import select

from app.models.drug_ingredient import DrugIngredient
from app.models.drug_master import DrugMaster
from app.models.hira import HiraGenCode, HiraGenIngredient, HiraItemGenCode
from tests.factories import make_drug


async def _hira(session, drug, gen_code, components, *, atc=None, cancelled_on=None):
    session.add(HiraItemGenCode(item_seq=drug.item_seq, gen_code=gen_code, atc_code=atc, cancelled_on=cancelled_on))
    session.add(HiraGenCode(gen_code=gen_code, form_name="정제,저작정", route="내복"))
    await session.flush()  # 성분 행의 외래 키보다 일반명코드가 먼저 저장돼야 한다
    for seq, (name, strength, unit) in enumerate(components, 1):
        session.add(HiraGenIngredient(gen_code=gen_code, seq=seq, ingr_name=name, strength=strength, unit=unit))
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

    rows = await _rows(session_factory)
    assert rows["성분만아는약"].ingredient_status == "hira_only" and rows["성분만아는약"].judgeable is False
    assert rows["성분만아는약"].dur_ingr_codes == []
    assert rows["정보없는약"].ingredient_status == "none" and rows["정보없는약"].judgeable is False
    assert rows["정보없는약"].hira_components == [] and rows["정보없는약"].atc_code is None


async def test_master_ignores_cancelled_hira_items(session_factory):
    async with session_factory() as session:
        drug = await make_drug(session, "취소된품목")
        await _hira(session, drug, "T00003ATB", [("old ingredient", "5", "mg")], atc="X99", cancelled_on=date(2020, 1, 1))

    row = (await _rows(session_factory))["취소된품목"]
    assert row.hira_components == [] and row.atc_code is None and row.ingredient_status == "none"


async def test_master_follows_source_changes_without_any_refresh(session_factory):
    """사본이 없으니 원천이 바뀌면 뷰가 바로 따라간다 — 갱신 단계가 없다."""
    async with session_factory() as session:
        drug = await make_drug(session, "바로반영")
        assert (await _rows(session_factory))["바로반영"].ingredient_status == "none"
        await _hira(session, drug, "T00004ATB", [("later added", "1", "g")])

    assert (await _rows(session_factory))["바로반영"].ingredient_status == "hira_only"

    async with session_factory() as session:
        session.add(DrugIngredient(drug_id=drug.id, ingr_code="D000147", ingr_kor="아세트아미노펜", source="dur"))
        await session.commit()

    row = (await _rows(session_factory))["바로반영"]
    assert row.ingredient_status == "dur_resolved" and row.dur_ingr_codes == ["D000147"]


async def test_master_has_one_row_per_drug_and_is_read_only(session_factory):
    """약 1개당 정확히 1행이고, 뷰라서 쓸 수 없다(원천이 유일한 저장소)."""
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with session_factory() as session:
        await make_drug(session, "약A")
        await make_drug(session, "약B")
    assert sorted(await _rows(session_factory)) == ["약A", "약B"]

    async with session_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("DELETE FROM drugs_master"))
