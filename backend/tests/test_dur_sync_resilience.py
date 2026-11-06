"""공공데이터 동기화의 조용한 결함 회귀 테스트.

1. 페이지 요청이 재시도 끝에 실패하면 건너뛰지 않고 그 페이지를 체크포인트로 남긴 채 중단하며,
   재실행 시 거기서 이어받는다(건너뛰면 규칙이 빠진 채 "완료"로 끝난다).
2. 이미 있는 성분쌍 규칙도 원천이 금기 사유 문장을 고치면 갱신하고, 낡은 risk_tags 는 비운다.

공공 API 는 부르지 않는다 — `_fetch_page` 를 가짜로 바꿔 페이지별 응답을 흉내 낸다.
"""
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.dur_ingredient_rule import DurIngredientContraindication, DurItemPregnancyTaboo
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
        with pytest.raises(RuntimeError, match="page 2"):
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
    (실패 횟수 제한이 없으면 API 가 죽을 때 페이지 번호만 올리며 끝없이 돈다.)"""
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
            await svc._sync_endpoint("http://x", handler, source="test", label="테스트", size=2)

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
            await svc._run_multi_endpoint_sync({"테스트": ("op", None)}, handler, source="test", size=2)

    assert fetched == [1, 2]


async def test_empty_page_before_the_last_page_is_a_quota_stop_not_eof(session_factory):
    """할당량 초과는 HTTP 200 + 빈 body로 와서 정상 끝처럼 보인다. totalCount상 아직 마지막
    페이지가 아니면 "완료"로 끝내지 말고 중단해야 한다(모든 동기화가 같은 루프를 쓴다)."""
    async with session_factory() as session:
        svc = PublicDataService(session)

        async def fake_fetch(client, url, params, retries=5):
            return {1: _page(2, total=10), 2: _page(0, total=10)}.get(params["pageNo"])

        async def handler(item):
            pass

        svc._fetch_page = fake_fetch
        with pytest.raises(RuntimeError, match="빈 응답"):
            await svc._sync_endpoint("http://x", handler, source="test", label="테스트", size=2)


async def test_insert_once_inserts_skips_and_overwrites(session_factory):
    """같은 키가 수천 번 다시 나오는 순회용 헬퍼: 처음엔 넣고, 같은 실행의 반복은 건너뛰고,
    overwrite면 새 실행에서 원천 값으로 갱신한다."""
    row = {"item_seq": "S1", "ingr_code": "D1", "ingr_kor": "성분", "prohibit_content": "처음", "remark": None}
    key = ("item_seq", "ingr_code")

    async with session_factory() as session:
        svc = PublicDataService(session)
        await svc._insert_once(DurItemPregnancyTaboo, key, row)
        await svc._insert_once(DurItemPregnancyTaboo, key, {**row, "prohibit_content": "같은 실행의 반복"})
        await session.commit()

    async with session_factory() as session:
        assert (await session.scalar(select(DurItemPregnancyTaboo))).prohibit_content == "처음"

    async with session_factory() as session:  # 새 실행: overwrite 아니면 그대로
        svc = PublicDataService(session)
        await svc._insert_once(DurItemPregnancyTaboo, key, {**row, "prohibit_content": "무시됨"})
        await session.commit()
    async with session_factory() as session:
        assert (await session.scalar(select(DurItemPregnancyTaboo))).prohibit_content == "처음"

    async with session_factory() as session:  # 새 실행 + overwrite: 갱신
        svc = PublicDataService(session)
        await svc._insert_once(DurItemPregnancyTaboo, key, {**row, "prohibit_content": "고쳐짐"}, overwrite=True)
        await session.commit()
    async with session_factory() as session:
        rows = (await session.scalars(select(DurItemPregnancyTaboo))).all()
        assert [r.prohibit_content for r in rows] == ["고쳐짐"]


async def test_dur_row_handlers_write_rules_and_ingredient_links(session_factory):
    """실제 응답 모양의 행을 핸들러에 넣어, 약 생성·성분 연결·규칙 적재가 DB까지 닿는지 본다."""
    from app.models.drug import Drug
    from app.models.drug_ingredient import DrugIngredient
    from app.models.dur_ingredient_rule import DurIngredientAgeCaution, DurIngredientEffectGroup

    contra_row = {
        "ITEM_SEQ": "100", "ITEM_NAME": "가약", "INGR_CODE": "D2", "INGR_KOR_NAME": "성분2",
        "MIXTURE_ITEM_SEQ": "200", "MIXTURE_ITEM_NAME": "나약", "MIXTURE_INGR_CODE": "D1",
        "MIXTURE_INGR_KOR_NAME": "성분1", "PROHBT_CONTENT": "함께 쓰면 안 됨",
    }
    async with session_factory() as session:
        svc = PublicDataService(session)
        await svc._upsert_dur_contraindication(contra_row)
        await svc._upsert_dur_contraindication(contra_row)  # 같은 행이 반복돼도 한 번만
        await svc._upsert_efcy_dplct(
            {"ITEM_SEQ": "100", "ITEM_NAME": "가약", "INGR_CODE": "D2", "DUR_SEQ": "7", "EFFECT_NAME": "해열"})
        await svc._handle_age_caution_item(
            {"ITEM_SEQ": "300", "ITEM_NAME": "다약", "INGR_CODE": "D3", "INGR_NAME": "성분3",
             "PROHBT_CONTENT": "12세 미만 투여 금기"}, "age_taboo")
        await svc._handle_pregnancy_taboo_item(
            {"ITEM_SEQ": "300", "ITEM_NAME": "다약", "INGR_CODE": "D3", "INGR_NAME": "성분3",
             "PROHBT_CONTENT": '"1등급"', "REMARK": "경구"})
        await svc._upsert_dur_contraindication({"ITEM_NAME": "이름만 있음"})  # 짝이 없으면 건너뜀
        await session.commit()

    async with session_factory() as session:
        rule = await session.scalar(select(DurIngredientContraindication))
        assert (rule.ingr_code_a, rule.ingr_code_b) == ("D1", "D2")        # 정규 순서 a<b
        assert (rule.ingr_kor_a, rule.ingr_kor_b) == ("성분1", "성분2")     # 이름도 같이 뒤집힘
        assert len((await session.scalars(select(DurIngredientContraindication))).all()) == 1

        drugs = {d.item_seq: d for d in (await session.scalars(select(Drug))).all()}
        assert set(drugs) == {"100", "200", "300"}
        links = {(d.drug_id, d.ingr_code) for d in (await session.scalars(select(DrugIngredient))).all()}
        assert links == {(drugs["100"].id, "D2"), (drugs["200"].id, "D1"), (drugs["300"].id, "D3")}

        group = await session.scalar(select(DurIngredientEffectGroup))
        assert (group.ingr_code, group.dur_seq, group.effect_name) == ("D2", "7", "해열")

        age = await session.scalar(select(DurIngredientAgeCaution))
        # 품목정보 문구의 "12세 미만"은 읽지 않는다 — 나이 기준은 성분정보 AGE_BASE만 쓴다
        assert (age.rule_type, age.age_threshold, age.age_unit, age.age_direction) == ("age_taboo", None, None, None)

        pregnancy = await session.scalar(select(DurItemPregnancyTaboo))
        assert (pregnancy.item_seq, pregnancy.prohibit_content, pregnancy.remark) == ("300", "1등급", "경구")


async def test_age_threshold_comes_only_from_age_base(session_factory):
    """나이 기준은 성분정보 AGE_BASE만 쓴다 — 동기화가 기존 값을 비우고 다시 채운다.
    기준이 제형별로 갈리는 성분(레보세티리진 6세/1세)·성분정보에 없는 성분은 판정에서 빠진다."""
    from app.models.dur_ingredient_rule import DurIngredientAgeCaution
    from tests.factories import make_ingr_age_caution

    async with session_factory() as session:
        for code in ("D1", "D2", "D3"):  # 예전 품목정보 문구에서 뽑아 둔 값
            await make_ingr_age_caution(session, code, "age_taboo", age_threshold=12, age_unit="세", age_direction="미만")
        svc = PublicDataService(session)
        svc._ingr_rows = {label: [] for label in svc.INGR_OPS}
        row = {"DEL_YN": "정상", "INGR_NAME": "성분"}
        svc._ingr_rows["특정연령대금기"] = [
            {**row, "INGR_CODE": "D1", "AGE_BASE": "6세 미만"},
            {**row, "INGR_CODE": "D2", "AGE_BASE": "6세 미만"},
            {**row, "INGR_CODE": "D2", "AGE_BASE": "1세 미만"},
        ]
        await svc._write_ingredient_rules()
        await session.commit()

    async with session_factory() as session:
        got = {r.ingr_code: (r.age_threshold, r.age_unit, r.age_direction)
               for r in (await session.scalars(select(DurIngredientAgeCaution))).all()}
    assert got == {"D1": (6, "세", "미만"), "D2": (None, None, None), "D3": (None, None, None)}
