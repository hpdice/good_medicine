"""허가정보 상세 배치 적재(backfill_details) — 실제 API는 부르지 않고 `_fetch`를 가짜로 바꿔 검증한다."""
from sqlalchemy import select

from app.config import settings
from app.models.drug import Drug
from app.services.drug_detail_service import DrugDetailService, _quota, backfill_details
from tests.factories import make_drug

_EE = (
    '<DOC title="효능효과" type="EE"><SECTION title=""><ARTICLE title="">'
    "<PARAGRAPH><![CDATA[골관절증의 증상 완화]]></PARAGRAPH></ARTICLE></SECTION></DOC>"
)


def _fake(monkeypatch, result):
    calls: list[str] = []

    async def fetch(self, item_seq):
        calls.append(item_seq)
        return result

    monkeypatch.setattr(DrugDetailService, "_fetch", fetch)
    monkeypatch.setattr(settings, "PUBLIC_DATA_API_KEY", "test-key")
    return calls


async def _fetched(session_factory):
    async with session_factory() as session:
        return {d.item_name: d for d in (await session.execute(select(Drug))).scalars()}


async def test_backfill_fills_text_and_marks_fetched(session_factory, monkeypatch):
    calls = _fake(monkeypatch, {"EE_DOC_DATA": _EE})
    async with session_factory() as session:
        await make_drug(session, "약A")
        await make_drug(session, "약B")
    res = await backfill_details(session_factory, limit=10, concurrency=2, log=lambda _: None)
    assert (res["candidates"], res["done"], res["failed"], res["stopped"]) == (2, 2, 0, False)
    assert len(calls) == 2
    drugs = await _fetched(session_factory)
    assert all(d.efcy_qesitm == "골관절증의 증상 완화" and d.detail_fetched_at for d in drugs.values())


async def test_backfill_picks_drugs_without_text_first_and_respects_limit(session_factory, monkeypatch):
    _fake(monkeypatch, {"EE_DOC_DATA": _EE})
    async with session_factory() as session:
        has_text = await make_drug(session, "가_이미설명있음")
        has_text.efcy_qesitm = "기존 효능"
        await session.commit()
        await make_drug(session, "나_설명없음")
    res = await backfill_details(session_factory, limit=1, concurrency=1, log=lambda _: None)
    assert res["candidates"] == 1
    drugs = await _fetched(session_factory)
    assert drugs["나_설명없음"].detail_fetched_at is not None  # 이름순으론 뒤여도 텍스트 없는 약이 먼저
    assert drugs["가_이미설명있음"].detail_fetched_at is None


async def test_backfill_skips_already_fetched_so_it_can_resume(session_factory, monkeypatch):
    calls = _fake(monkeypatch, {"EE_DOC_DATA": _EE})
    async with session_factory() as session:
        await make_drug(session, "약A")
        await make_drug(session, "약B")
    await backfill_details(session_factory, limit=1, concurrency=1, log=lambda _: None)
    res = await backfill_details(session_factory, limit=10, concurrency=1, log=lambda _: None)
    assert res["candidates"] == 1 and len(calls) == 2  # 두 번째 실행은 남은 1건만


async def test_backfill_stops_after_consecutive_failures_and_leaves_drugs_unmarked(session_factory, monkeypatch):
    calls = _fake(monkeypatch, None)  # API 실패(한도 초과·장애)
    async with session_factory() as session:
        for i in range(8):
            await make_drug(session, f"약{i}")
    res = await backfill_details(session_factory, limit=100, concurrency=1, max_consecutive_failures=3,
                                 log=lambda _: None)
    assert res["stopped"] is True and res["done"] == 0 and res["failed"] == 3
    assert len(calls) == 3  # 실패가 이어지면 나머지는 부르지 않는다
    assert all(d.detail_fetched_at is None for d in (await _fetched(session_factory)).values())


async def test_backfill_without_api_key_does_nothing(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_DATA_API_KEY", "")
    res = await backfill_details(session_factory, limit=10, log=lambda _: None)
    assert res["stopped"] is True and res["done"] == 0


async def test_backfill_stops_when_remaining_quota_falls_below_reserve(session_factory, monkeypatch):
    """앱의 실시간 보충용으로 남겨 둔 호출 수 아래로 내려가면 배치는 멈춘다."""
    async def fetch(self, item_seq):
        _quota["remaining"] = 900  # 응답 헤더의 남은 호출 수
        return {"EE_DOC_DATA": _EE}

    monkeypatch.setattr(DrugDetailService, "_fetch", fetch)
    monkeypatch.setattr(settings, "PUBLIC_DATA_API_KEY", "test-key")
    async with session_factory() as session:
        for i in range(5):
            await make_drug(session, f"약{i}")
    res = await backfill_details(session_factory, limit=100, concurrency=2, reserve=1500, log=lambda _: None)
    assert res["quota_low"] is True and res["done"] == 1  # 첫 건으로 확인하고 멈춘다
    fetched = [d for d in (await _fetched(session_factory)).values() if d.detail_fetched_at]
    assert len(fetched) == 1
    _quota["remaining"] = None
