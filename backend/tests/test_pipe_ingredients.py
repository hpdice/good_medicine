"""허가정보 상세의 `|` 구분 복합제 성분 — 쪼개서 모든 성분을 맺고, 이미 한 이름으로 묶인 약은 바로잡는다."""
from sqlalchemy import select

from app.config import settings
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.models.dur_ingredient_master import DurIngredientMaster
from app.services.drug_detail_service import DrugDetailService
from app.services.public_data_service import PublicDataService
from app.services.public_data_service.helpers import _parse_main_ingr
from tests.factories import make_drug

A, B, C = ("D900001", "테스트성분가"), ("D900002", "테스트성분나"), ("D900003", "테스트성분다")
PIPE = f"[M100001]{A[1]}|[M100002]{B[1]}|[M100003]{C[1]}"


async def _master(session):
    for code, kor in (A, B, C):
        session.add(DurIngredientMaster(ingr_code=code, ingr_kor=kor, ingr_eng=kor, ingr_eng_norm=kor, mix_type="단일"))
    await session.commit()


async def _rows(session_factory, drug_id):
    async with session_factory() as session:
        return sorted((await session.execute(
            select(DrugIngredient.ingr_code, DrugIngredient.ingr_kor, DrugIngredient.source)
            .where(DrugIngredient.drug_id == drug_id)
        )).all())


def test_parse_main_ingr_splits_slash_and_pipe_and_strips_codes():
    assert [i["kor"] for i in _parse_main_ingr("[M1]가나다/[M2]라마바")] == ["가나다", "라마바"]  # 허가 목록 형식 그대로
    parsed = _parse_main_ingr(PIPE)
    assert [i["kor"] for i in parsed] == [A[1], B[1], C[1]]
    assert [i["dur_code"] for i in parsed] == ["M100001", "M100002", "M100003"]


async def test_detail_with_pipe_separated_combination_links_every_ingredient(session_factory, monkeypatch):
    async def fetch(self, item_seq):
        return {"MAIN_ITEM_INGR": PIPE}

    monkeypatch.setattr(DrugDetailService, "_fetch", fetch)
    monkeypatch.setattr(settings, "PUBLIC_DATA_API_KEY", "test-key")
    async with session_factory() as session:
        await _master(session)
        drug = await make_drug(session, "복합제")
        assert await DrugDetailService(session).ensure_detail(drug) is True

    assert await _rows(session_factory, drug.id) == [
        (A[0], A[1], "permit_detail"), (B[0], B[1], "permit_detail"), (C[0], C[1], "permit_detail"),
    ]
    async with session_factory() as session:
        saved = await session.get(Drug, drug.id)
        assert [i["kor"] for i in saved.ingr_name] == [A[1], B[1], C[1]]


async def test_repair_fixes_drugs_stored_with_joined_name(session_factory):
    """이미 한 이름으로 묶여 저장된 약 — 이름을 쪼개고 잘못된 행을 지운 뒤 모든 성분을 맺는다."""
    async with session_factory() as session:
        await _master(session)
        drug = await make_drug(session, "깨진복합제")
        joined = f"{A[1]}|[M100002]{B[1]}|[M100003]{C[1]}"
        drug.main_item_ingr = PIPE
        drug.ingr_name = [{"kor": joined, "eng": "", "amount": "", "dur_code": "M100001"}]
        session.add(DrugIngredient(drug_id=drug.id, ingr_code=A[0], ingr_kor=joined, source="permit_detail"))
        other = await make_drug(session, "멀쩡한약", ingredients=[(A[0], A[1])])
        other.main_item_ingr = f"[M100001]{A[1]}"
        other.ingr_name = [{"kor": A[1], "eng": "", "amount": "", "dur_code": "M100001"}]
        await session.commit()
        assert await PublicDataService(session).repair_pipe_main_ingr() == 1  # 멀쩡한 약은 건드리지 않는다

    assert await _rows(session_factory, drug.id) == [
        (A[0], A[1], "permit_detail"), (B[0], B[1], "permit_detail"), (C[0], C[1], "permit_detail"),
    ]
    assert await _rows(session_factory, other.id) == [(A[0], A[1], "dur")]


async def test_repair_also_fixes_drugs_with_only_joined_names_and_no_raw_text(session_factory):
    """원문(main_item_ingr)이 없고 이름만 묶여 저장된 약(아니스펜8시간이알서방정 같은 경우)도 쪼갠다."""
    async with session_factory() as session:
        await _master(session)
        drug = await make_drug(session, "이름만묶인약")
        drug.ingr_name = [{"kor": f"{A[1]}|[M100002]{B[1]}|[M100001]{A[1]}", "eng": "", "amount": "", "dur_code": "M100001"}]
        await session.commit()
        assert await PublicDataService(session).repair_pipe_main_ingr() == 1

    async with session_factory() as session:
        assert [i["kor"] for i in (await session.get(Drug, drug.id)).ingr_name] == [A[1], B[1]]  # 중복 이름은 하나만
    assert await _rows(session_factory, drug.id) == [(A[0], A[1], "permit_detail"), (B[0], B[1], "permit_detail")]
