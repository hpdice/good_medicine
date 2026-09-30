"""공공데이터 동기화의 조용한 결함 회귀 테스트 (2026-09-30).

1. 페이지 요청이 재시도 끝에 실패하면 그 페이지를 건너뛰고(page += 1) 계속해, 규칙이 빠진 채
   "완료"로 끝났다 → 이제 그 페이지를 체크포인트로 남기고 중단, 재실행 시 거기서 이어받는다.
2. 이미 있는 성분쌍 규칙은 "있으면 건너뜀"이라 원천이 금기 사유 문장을 고쳐도 반영되지 않았다
   → 문장이 바뀌면 갱신하고, 낡은 risk_tags 는 비운다.

공공 API 는 부르지 않는다 — `_fetch_page` 를 가짜로 바꿔 페이지별 응답을 흉내 낸다.
"""
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.dur_ingredient_rule import DurIngredientContraindication
from app.services.public_data_service import PublicDataService
from tests.factories import make_ingr_contraindication


def _page(n_items: int, total: int = 5) -> dict:
    return {"body": {"items": [{"row": i} for i in range(n_items)], "totalCount": total}}


def _service(session, responses: dict, fetched: list, upserted: list) -> PublicDataService:
    svc = PublicDataService(session)
    svc.DUR_PAGE_SIZE = 2  # 페이지당 2행이면 "가득 찬 페이지" → 다음 페이지로 진행

    async def fake_fetch(client, url, params, retries=5):
        page = params["pageNo"]
        fetched.append(page)
        return responses.get(page)

    async def fake_upsert(item):
        upserted.append(item)

    svc._fetch_page = fake_fetch
    svc._upsert_dur_contraindication = fake_upsert
    return svc


async def test_failed_page_is_not_skipped_and_resume_starts_there(session_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_STATE_DIR", str(tmp_path))

    # 1차 실행: 1페이지 정상, 2페이지 실패(재시도 소진), 3페이지는 정상이지만 도달하면 안 됨
    fetched, upserted = [], []
    async with session_factory() as session:
        svc = _service(session, {1: _page(2), 2: None, 3: _page(1)}, fetched, upserted)
        with pytest.raises(RuntimeError, match="페이지 2"):
            await svc._sync_dur_contraindications()

    assert fetched == [1, 2]                 # 3페이지로 건너뛰지 않았다
    assert len(upserted) == 2                # 1페이지 분량만 적재
    checkpoint = tmp_path / "dur_contraindications_checkpoint.txt"
    assert checkpoint.read_text() == "2"     # 실패한 페이지를 이어받을 위치로 남김

    # 2차 실행: 2페이지가 이제 정상(마지막 페이지) → 정확히 2페이지부터 시작해 완료
    fetched, upserted = [], []
    async with session_factory() as session:
        svc = _service(session, {2: _page(1)}, fetched, upserted)
        count = await svc._sync_dur_contraindications()

    assert fetched == [2]
    assert count == 1
    assert not checkpoint.exists()           # 완주하면 체크포인트 삭제


async def test_changed_prohibit_content_updates_rule_and_clears_risk_tags(session_factory):
    async with session_factory() as session:
        await make_ingr_contraindication(
            session, "D000001", "D000002", prohibit_content="옛 금기 사유", risk_tags=["옛 태그"],
        )

    async with session_factory() as session:
        svc = PublicDataService(session)
        await svc._upsert_ingr_contraindication(
            "D000001", "D000002", "성분A", "성분B", prohibit_content="고쳐진 금기 사유", remark=None,
        )
        await session.commit()
        assert svc._updated_ingr_contra == 1

    async with session_factory() as session:
        rule = await session.scalar(select(DurIngredientContraindication))
        assert rule.prohibit_content == "고쳐진 금기 사유"
        assert rule.risk_tags is None         # extract_risk_tags 가 새 문장으로 다시 뽑도록


async def test_same_prohibit_content_is_left_untouched(session_factory):
    async with session_factory() as session:
        await make_ingr_contraindication(
            session, "D000003", "D000004", prohibit_content="같은 문장", risk_tags=["태그"],
        )

    async with session_factory() as session:
        svc = PublicDataService(session)
        await svc._upsert_ingr_contraindication(
            "D000003", "D000004", "성분A", "성분B", prohibit_content="같은 문장", remark=None,
        )
        await session.commit()
        assert svc._updated_ingr_contra == 0

    async with session_factory() as session:
        rule = await session.scalar(select(DurIngredientContraindication))
        assert rule.risk_tags == ["태그"]      # 바뀐 게 없으면 태그 유지


async def test_simple_paginated_sync_stops_instead_of_skipping(session_factory):
    """e약은요·허가정보·효능군중복이 쓰는 공통 루프도 실패 페이지를 건너뛰면 안 된다.
    (이전엔 실패 횟수 제한도 없어, API 가 죽으면 페이지 번호만 올리며 끝없이 돌았다.)"""
    fetched, handled = [], []
    async with session_factory() as session:
        svc = PublicDataService(session)

        async def fake_fetch(client, url, params, retries=5):
            fetched.append(params["pageNo"])
            return {1: _page(2), 2: None, 3: _page(1)}.get(params["pageNo"])

        async def handler(item):
            handled.append(item)

        svc._fetch_page = fake_fetch
        with pytest.raises(RuntimeError, match="page 2"):
            await svc._run_simple_paginated_sync("http://x", handler, "test", "테스트", page_size=2)

    assert fetched == [1, 2]
    assert len(handled) == 2


async def test_multi_endpoint_sync_stops_instead_of_skipping(session_factory):
    fetched = []
    async with session_factory() as session:
        svc = PublicDataService(session)

        async def fake_fetch(client, url, params, retries=5):
            fetched.append(params["pageNo"])
            return {1: _page(2), 2: None, 3: _page(1)}.get(params["pageNo"])

        async def handler(item, extra):
            pass

        svc._fetch_page = fake_fetch
        with pytest.raises(RuntimeError, match="page 2"):
            await svc._run_multi_endpoint_sync(
                {"테스트": ("op", None)}, handler,
                error_label="테스트", source_prefix="test", retry_hint="sync.py x", page_size=2,
            )

    assert fetched == [1, 2]
