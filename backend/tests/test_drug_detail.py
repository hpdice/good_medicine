"""허가정보 상세 API 온디맨드 보강 — 실제 API는 부르지 않고 `_fetch`를 가짜로 바꿔 검증한다."""
from sqlalchemy import select

from app.config import settings
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.services.drug_detail_service import DrugDetailService
from app.services.public_data_service.helpers import permit_doc_to_text
from tests.factories import make_drug, register_and_login

_EE = (
    '<DOC title="효능효과" type="EE"><SECTION title=""><ARTICLE title="">'
    "<PARAGRAPH><![CDATA[골관절증의 증상 완화]]></PARAGRAPH></ARTICLE></SECTION></DOC>"
)
_UD = (
    '<DOC title="용법용량" type="UD"><SECTION title=""><ARTICLE title="">'
    "<PARAGRAPH><![CDATA[성인 1일 2회, 1회 1정 복용]]></PARAGRAPH></ARTICLE></SECTION></DOC>"
)


def _nb(*articles: tuple[str, str]) -> str:
    body = "".join(
        f'<ARTICLE title="{t}"><PARAGRAPH><![CDATA[{p}]]></PARAGRAPH></ARTICLE>' for t, p in articles
    )
    return f'<DOC title="사용상의주의사항" type="NB"><SECTION title="">{body}</SECTION></DOC>'


def _fake_fetch(monkeypatch, item: dict | None):
    calls: list[str] = []

    async def fetch(self, item_seq):
        calls.append(item_seq)
        return item

    monkeypatch.setattr(DrugDetailService, "_fetch", fetch)
    monkeypatch.setattr(settings, "PUBLIC_DATA_API_KEY", "test-key")
    return calls


def test_permit_doc_to_text_titles_and_paragraphs():
    text = permit_doc_to_text(_nb(("1. 다음 환자에는 투여하지 말 것", "과민반응 환자"), ("2. 부작용", "구역")))
    assert text == "1. 다음 환자에는 투여하지 말 것\n과민반응 환자\n2. 부작용\n구역"


def test_permit_doc_to_text_keeps_full_text_without_truncation_marker():
    """전문을 그대로 둔다 — 예전엔 1500자에서 자르고 '이하 생략'을 붙였다(잘린 뒤는 볼 수 없었음)."""
    doc = _nb(*[(f"{i}. 항목", "가" * 600) for i in range(1, 8)])  # 약 4,300자
    text = permit_doc_to_text(doc) or ""
    assert "7. 항목" in text and text.count("가") == 7 * 600
    assert "이하 생략" not in text


def test_permit_doc_to_text_unescapes_html_entities():
    """CDATA에 날것으로 남은 `&nbsp;`가 화면에 그대로 보이던 문제."""
    doc = _nb(("2. 신중", "2)&nbsp;고지단백혈증 &amp; 당뇨병성&nbsp;&nbsp;고지질혈증"))
    text = permit_doc_to_text(doc) or ""
    assert "&nbsp;" not in text and "&amp;" not in text
    assert "2) 고지단백혈증 & 당뇨병성 고지질혈증" in text


def test_permit_doc_to_text_handles_empty_and_broken_xml():
    assert permit_doc_to_text(None) is None
    assert permit_doc_to_text("   ") is None
    assert permit_doc_to_text("<DOC><PARAGRAPH>깨진 문서") == "깨진 문서"


async def test_ensure_detail_fills_empty_fields_and_marks_fetched(session_factory, monkeypatch):
    calls = _fake_fetch(monkeypatch, {
        "EE_DOC_DATA": _EE, "UD_DOC_DATA": _UD, "NB_DOC_DATA": _nb(("1. 금기", "과민반응")),
        "MAIN_ITEM_INGR": "[M254177]당귀·목과엑스",
    })
    async with session_factory() as session:
        drug = await make_drug(session, "레이본정")
        assert await DrugDetailService(session).ensure_detail(drug) is True
        await session.refresh(drug)
        assert drug.efcy_qesitm == "골관절증의 증상 완화"
        assert drug.use_method_qesitm == "성인 1일 2회, 1회 1정 복용"
        assert "과민반응" in (drug.atpn_qesitm or "")
        assert drug.main_item_ingr == "[M254177]당귀·목과엑스"
        assert drug.ingr_name is not None and drug.ingr_name[0]["kor"] == "당귀·목과엑스"
        assert drug.detail_fetched_at is not None

        # 두 번째 호출은 API를 다시 부르지 않는다
        assert await DrugDetailService(session).ensure_detail(drug) is False
        assert len(calls) == 1


async def test_ensure_detail_never_overwrites_existing_text(session_factory, monkeypatch):
    _fake_fetch(monkeypatch, {"EE_DOC_DATA": _EE, "UD_DOC_DATA": _UD})
    async with session_factory() as session:
        drug = await make_drug(session, "기존정")
        drug.efcy_qesitm = "e약은요 효능 문구"
        await session.commit()
        await DrugDetailService(session).ensure_detail(drug)
        await session.refresh(drug)
        assert drug.efcy_qesitm == "e약은요 효능 문구"
        assert drug.use_method_qesitm == "성인 1일 2회, 1회 1정 복용"


async def test_ensure_detail_resolves_dur_ingredient_by_name(session_factory, monkeypatch):
    _fake_fetch(monkeypatch, {"MAIN_ITEM_INGR": "[M000001]트리메부틴말레산염"})
    async with session_factory() as session:
        # DUR에서 이미 알려진 성분(다른 약 경유) — 허가정보 M코드가 아니라 D코드로 맺혀야 한다
        await make_drug(session, "다른약", ingredients=[("D009999", "트리메부틴")])
        drug = await make_drug(session, "뉴부틴서방정")
        await DrugDetailService(session).ensure_detail(drug)
        rows = (await session.execute(
            select(DrugIngredient).where(DrugIngredient.drug_id == drug.id)
        )).scalars().all()
        assert [(r.ingr_code, r.source) for r in rows] == [("D009999", "permit_detail")]


async def test_ensure_detail_leaves_unknown_ingredient_unresolved(session_factory, monkeypatch):
    """DUR에 없는 성분은 억지로 맺지 않는다 — 규칙이 없는 약일 뿐 오류가 아니다."""
    _fake_fetch(monkeypatch, {"MAIN_ITEM_INGR": "[M254177]당귀·목과엑스"})
    async with session_factory() as session:
        await make_drug(session, "다른약", ingredients=[("D009999", "아세트아미노펜")])
        drug = await make_drug(session, "레이본정")
        await DrugDetailService(session).ensure_detail(drug)
        rows = (await session.execute(
            select(DrugIngredient).where(DrugIngredient.drug_id == drug.id)
        )).scalars().all()
        assert rows == []


async def test_ensure_detail_api_failure_does_not_mark_fetched(session_factory, monkeypatch):
    _fake_fetch(monkeypatch, None)  # 호출 실패
    async with session_factory() as session:
        drug = await make_drug(session, "실패정")
        assert await DrugDetailService(session).ensure_detail(drug) is False
        await session.refresh(drug)
        assert drug.detail_fetched_at is None  # 다음에 다시 시도할 수 있어야 한다


async def test_ensure_detail_skips_without_api_key(session_factory, monkeypatch):
    calls = _fake_fetch(monkeypatch, {"EE_DOC_DATA": _EE})
    monkeypatch.setattr(settings, "PUBLIC_DATA_API_KEY", "")
    async with session_factory() as session:
        drug = await make_drug(session, "키없음정")
        assert await DrugDetailService(session).ensure_detail(drug) is False
        assert calls == []


async def test_adding_to_medicine_box_fills_detail_in_response(client, session_factory, monkeypatch):
    _fake_fetch(monkeypatch, {"EE_DOC_DATA": _EE})
    async with session_factory() as session:
        drug = await make_drug(session, "레이본정")
    token = await register_and_login(client)
    res = await client.post(
        "/medicine-box", json={"drug_id": str(drug.id)}, headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 201, res.text
    assert res.json()["drug"]["efcy_qesitm"] == "골관절증의 증상 완화"


async def test_adding_to_medicine_box_survives_detail_failure(client, session_factory, monkeypatch):
    async def boom(self, item_seq):
        raise RuntimeError("API 폭발")

    monkeypatch.setattr(DrugDetailService, "_fetch", boom)
    monkeypatch.setattr(settings, "PUBLIC_DATA_API_KEY", "test-key")
    async with session_factory() as session:
        drug = await make_drug(session, "레이본정")
    token = await register_and_login(client)
    res = await client.post(
        "/medicine-box", json={"drug_id": str(drug.id)}, headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 201, res.text
    async with session_factory() as session:
        assert (await session.get(Drug, drug.id)).detail_fetched_at is None
