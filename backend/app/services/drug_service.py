import re
import uuid
from collections.abc import Iterable
from typing import Any, TypeVar

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import class_mapper

from app.core.exceptions import NotFoundError
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.models.dur_ingredient_master import DurIngredientMaster
from app.models.dur_ingredient_rule import (
    DurIngredientAgeCaution,
    DurIngredientContraindication,
    DurIngredientDoseCaution,
    DurIngredientEffectGroup,
    DurItemPregnancyTaboo,
)
from app.models.hira import HiraGenCode, HiraItemGenCode
from app.models.residual_interaction import ResidualInteraction
from app.services.public_data_service import _make_drug_key

# 정/캡슐 등 제형 접미사 뒤에 성분명이 오는 입력('와파린정', '메트포르민정500mg')을
# 처리하기 위해 제거할 제형 표현. 복합 표현이 먼저 매칭되도록 길이 내림차순으로 정렬한다.
_DOSAGE_FORM_SUFFIXES = sorted(
    [
        "이알서방정", "서방정", "장용정", "구강붕해정", "츄어블정", "발포정", "필름코팅정",
        "정제", "정", "캡슐", "산제", "산", "시럽", "현탁액", "액", "주사", "주",
        "크림", "연고", "겔", "패치", "좌제", "점안액", "점이액", "흡입액", "분말", "과립",
    ],
    key=len,
    reverse=True,
)
_TRAILING_DOSE_RE = re.compile(r'\d+\.?\d*(mg|mcg|g|iu|%)?$')


def _extract_ingredient_stem(name: str) -> str:
    """'와파린정', '메트포르민정500mg' 같은 입력에서 제형·용량을 제거해
    성분명 후보('와파린', '메트포르민')를 추출한다. 브랜드명이 성분명을
    괄호 안에 숨기는 경우(_make_drug_key가 괄호를 제거) drug_key/ILIKE
    매칭이 실패하므로, ingr_name 기반 매칭의 입력으로 사용한다.
    """
    s = _make_drug_key(name)
    s = _TRAILING_DOSE_RE.sub('', s)
    for suf in _DOSAGE_FORM_SUFFIXES:
        if len(s) > len(suf) and s.endswith(suf):
            s = s[: -len(suf)]
            break
    return s


def _ingredient_match_clause(stem: str):
    """브랜드명이 성분명을 괄호 안에 감춰서(예: '쿠파린정(와파린나트륨)') drug_key나
    전체 검색어 ILIKE가 실패하는 '성분명+제형' 입력을 위한 성분 기반 폴백.

    ingr_name JSONB는 전체 약품의 21%(7,628/35,324)에만 채워져 있어 그것만으로는
    커버리지가 낮다. item_name 자체에 성분명이 괄호로 표기되는 경우가 훨씬 많으므로
    (ingr_name 유무와 무관하게) item_name/simple_name에 대한 stem ILIKE를 함께 건다.
    """
    # jsonb_typeof 가드: ingr_name 이 JSON 배열이 아닐 때(NULL, 또는 JSONB `null` 스칼라 —
    # SQLAlchemy JSONB 기본이 none_as_null=False 라 미설정 시 'null' 스칼라가 됨)
    # jsonb_array_elements 가 "cannot extract elements from a scalar" 로 터지는 것을 막는다.
    ingr_jsonb_exists = text(
        "jsonb_typeof(drugs.ingr_name) = 'array' AND EXISTS ("
        "SELECT 1 FROM jsonb_array_elements(drugs.ingr_name) elem "
        "WHERE elem->>'kor' ILIKE :ingr_stem_pattern)"
    ).bindparams(ingr_stem_pattern=f"%{stem}%")
    pattern = f"%{stem}%"
    return or_(
        ingr_jsonb_exists,
        Drug.item_name.ilike(pattern),
        Drug.simple_name.ilike(pattern),
    )


def ingredient_alias_map(rows: Iterable[tuple[str, str | None, str | None]]) -> dict[str, str]:
    """DUR 성분 조회표 `(성분코드, 한글명, 단일|복합)` → {코드: 대표 코드}. 같은 성분인데 코드가 둘 이상인 것만 담는다.

    DUR은 한 성분에 코드를 여럿 쓰고 규칙을 코드마다 나눠 붙인다 — 케토롤락은 병용금기 34건이 D000274에,
    노인주의가 D001289에 있고, 같은 품목이 두 코드에 다 나온다(제형별 코드가 아니다). 약이 한쪽 코드만 받으면
    다른 쪽 규칙을 놓친다(실측: 펜타미딘 D001456 품목이 D000513의 병용금기 6건을 놓침). 한글명(공백 무시)과
    단일/복합이 같으면 같은 성분으로 보고, 가장 작은 코드를 대표로 쓴다."""
    groups: dict[tuple[str, str | None], set[str]] = {}
    for code, kor, mix_type in rows:
        key = (kor or "").replace(" ", "")
        if code and key:
            groups.setdefault((key, mix_type), set()).add(code)
    return {code: min(codes) for codes in groups.values() if len(codes) > 1 for code in codes}


_Row = TypeVar("_Row")


def _recoded(row: _Row, **changes: Any) -> _Row:
    """규칙 행의 성분코드만 대표 코드로 바꾼 사본. 세션에 붙지 않는 임시 객체라 DB에는 쓰이지 않는다."""
    if not changes:
        return row
    values = {attr.key: getattr(row, attr.key) for attr in class_mapper(type(row)).column_attrs}
    return type(row)(**{**values, **changes})


def _canonical_code(code: str, aliases: dict[str, str]) -> dict[str, str]:
    """`_recoded`에 넘길 변경분 — 대표 코드가 아니면 {'ingr_code': 대표 코드}, 맞으면 {}."""
    rep = aliases.get(code, code)
    return {"ingr_code": rep} if rep != code else {}


def _name_prefix(normalized_key: str) -> str:
    """정규화 키에서 첫 숫자(용량) 앞까지 — '가스핀정5mg' → '가스핀정'."""
    return re.split(r'\d', normalized_key)[0]


def _jamo_seq(text_: str) -> list[int]:
    """한글 음절을 초성·중성·종성 자모로 푼다. 한글이 아닌 글자는 코드 그대로(겹치지 않게 큰 수로)."""
    out: list[int] = []
    for ch in text_:
        offset = ord(ch) - 0xAC00
        if 0 <= offset < 11172:
            out.append(offset // 588)
            out.append(100 + offset % 588 // 28)
            if offset % 28:
                out.append(200 + offset % 28)
        else:
            out.append(1000 + ord(ch))
    return out


def _jamo_distance(a: str, b: str) -> int:
    """두 이름의 자모 단위 편집 거리. '페'↔'폐'(ㅔ↔ㅖ)·'베'↔'빼'(ㅂ↔ㅃ)는 1이다."""
    x, y = _jamo_seq(a), _jamo_seq(b)
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return prev[-1]


# OCR이 글자를 한두 자모만 틀리게 읽은 경우만 닮은 이름으로 본다 — 음절 수가 같고(삽입·누락은 안 봄),
# 다른 음절이 둘 이하이며 자모 거리가 이 값 이하. 트라이그램은 짧은 한글 이름('액티폐린정'↔'액티페린정')에서
# 공통 3글자 묶음이 거의 없어 못 잡는다.
_SLIP_MAX_JAMO = 2
_SLIP_MIN_LEN = 4


def _ocr_slip_distance(query: str, name: str) -> int | None:
    """`query`가 `name`을 OCR이 한두 자모만 틀리게 읽은 것이면 자모 거리, 아니면 None."""
    if len(query) != len(name) or len(query) < _SLIP_MIN_LEN or query == name:
        return None
    if sum(p != q for p, q in zip(query, name)) > 2:
        return None
    dist = _jamo_distance(query, name)
    return dist if dist <= _SLIP_MAX_JAMO else None


def _dosage_rank(drug: Drug, normalized_key: str, target_digits: str) -> int:
    """같은 이름·다른 용량 후보의 우선순위: 완전 일치 0, 용량 숫자가 서로 시작/포함 1, 그 외 2."""
    if drug.drug_key == normalized_key:
        return 0
    key_digits = re.search(r'\d+', drug.drug_key or "")
    if key_digits and (
        target_digits.startswith(key_digits.group()) or key_digits.group().startswith(target_digits)
    ):
        return 1
    return 2


def _export_last():
    """수출 전용 품목('판콜에이내복액(Pancold A …)(수출용)')은 국내 품목과 매칭키가 같아 순서가 정해지지 않았다 — 뒤로 보낸다."""
    return case((Drug.item_name.like("%수출용%"), 1), else_=0)


class DrugService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._aliases: dict[str, str] | None = None

    async def search(self, query: str, page: int = 1, limit: int = 20) -> list[Drug]:
        offset = (page - 1) * limit
        direct_match = or_(
            Drug.item_name.ilike(f"%{query}%"),
            Drug.simple_name.ilike(f"%{query}%"),
        )
        conditions = [direct_match]

        # 브랜드명이 성분명을 괄호 안에 숨겨('쿠파린정(와파린나트륨)') 위 ILIKE로
        # 잡히지 않는 성분명+제형 검색어('와파린정')를 위한 성분 기반 폴백.
        # 정확 매칭보다 뒤로 정렬해 더 넓은 폴백이 정확한 결과를 밀어내지 않게 한다.
        stem = _extract_ingredient_stem(query)
        has_ingredient_fallback = len(stem) >= 2 and stem != query
        if has_ingredient_fallback:
            conditions.append(_ingredient_match_clause(stem))

        order_expr = case((direct_match, 0), else_=1) if has_ingredient_fallback else None

        stmt = select(Drug).where(or_(*conditions))
        if order_expr is not None:
            stmt = stmt.order_by(order_expr, Drug.item_name)
        else:
            stmt = stmt.order_by(Drug.item_name)
        stmt = stmt.offset(offset).limit(limit)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, drug_id: uuid.UUID) -> Drug:
        drug = await self.db.get(Drug, drug_id)
        if not drug:
            raise NotFoundError("약품을 찾을 수 없습니다.")
        return drug

    async def get_drugs_by_ids(self, drug_ids: list[uuid.UUID]) -> dict[uuid.UUID, Drug]:
        stmt = select(Drug).where(Drug.id.in_(drug_ids))
        result = await self.db.execute(stmt)
        return {d.id: d for d in result.scalars().all()}

    async def get_residual_for_drug_list(
        self, drug_ids: list[uuid.UUID]
    ) -> list[ResidualInteraction]:
        """주어진 약품 ID 목록 내 모든 쌍의 잔여 폴백 상호작용(병용금기 + 효능군중복)을
        단일 쿼리로 조회. 성분코드 미해소 약이 낀 quick_check 호출에서만 쓰인다."""
        stmt = select(ResidualInteraction).where(
            ResidualInteraction.drug1_id.in_(drug_ids),
            ResidualInteraction.drug2_id.in_(drug_ids),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # 한 글자 오인식은 0.40~0.42('뉴부턴'→뉴부틴 0.40, '신플렉스'→신플랙스 0.42),
    # 의미 없는 입력('가나다라마정')은 0.2~0.3 — 0.38이 둘을 가른다.
    FUZZY_MIN_SIMILARITY = 0.38

    async def _slip_candidates(self, key: str) -> list[Drug]:
        """OCR이 자모 한두 개만 틀리게 읽은 이름과 같은 약 최대 3개(자모 거리 순) — `_ocr_slip_distance` 참고.
        용량 앞까지의 이름만 비교하고, 앞 단계가 빈손일 때만 타는 경로라 `drug_key` 전체(3.5만 건)를 읽어도 무시할 만하다."""
        name = _name_prefix(key)
        if len(name) < _SLIP_MIN_LEN:
            return []
        scored: list[tuple[int, bool, int, str, uuid.UUID]] = []
        for drug_id, drug_key, item_name in (await self.db.execute(
            select(Drug.id, Drug.drug_key, Drug.item_name)
        )).all():
            candidate = _name_prefix(drug_key or "")
            dist = _ocr_slip_distance(name, candidate)
            if dist is not None:
                scored.append((dist, "수출용" in (item_name or ""), len(drug_key or ""), candidate, drug_id))
        scored.sort(key=lambda s: s[:3])
        ids: list[uuid.UUID] = []
        seen: set[str] = set()
        for _, _, _, candidate, drug_id in scored:
            if candidate not in seen:  # 같은 이름에 용량만 다른 품목은 하나만
                seen.add(candidate)
                ids.append(drug_id)
        if not ids:
            return []
        by_id = await self.get_drugs_by_ids(ids[:3])
        return [by_id[i] for i in ids[:3] if i in by_id]

    async def _fuzzy_candidates(self, key: str) -> list[Drug]:
        """`drug_key`와 트라이그램 유사도가 높은 약 최대 3개(유사도 순).

        `word_similarity`는 짧은 검색어가 긴 `drug_key`('신플랙스세이프정500/20밀리그램')의
        앞부분과 얼마나 닮았는지를 보므로 뒤에 붙은 용량·성분 표기에 점수가 깎이지 않는다.
        `<%` 연산자(GIN 인덱스)는 기본 문턱 0.6이라 한 글자 오인식을 못 잡아, 점수를 직접 비교한다 —
        앞선 4단계가 모두 빈손일 때만 타는 경로라 전체 스캔(3.5만 건) 비용은 무시할 만하다."""
        if len(key) < 3:
            return []
        score = func.word_similarity(key, Drug.drug_key)
        rows = (await self.db.execute(
            select(Drug)
            .where(score >= self.FUZZY_MIN_SIMILARITY)
            .order_by(score.desc(), func.length(Drug.drug_key))
            .limit(3)
        )).scalars().all()
        return list(rows)

    async def _match_by_prefix(self, normalized_key: str) -> list[Drug]:
        """용량을 뗀 이름(첫 숫자 앞까지)으로 `drug_key` 접두 조회. 정확 일치가 있으면 그것이 맨 앞.
        예: '가스핀정5mg' → '가스핀정' 접두. 완전 일치도 접두 일치에 포함되므로 별도 단계가 필요 없다."""
        name_prefix = _name_prefix(normalized_key)
        if len(name_prefix) < 2:
            return []
        rows = list((await self.db.execute(
            select(Drug)
            .where(Drug.drug_key.startswith(name_prefix))
            .order_by(case((Drug.drug_key == normalized_key, 0), else_=1), _export_last(), Drug.drug_key)
            .limit(5)
        )).scalars().all())
        # 같은 이름에 용량만 다른 제품(파탁정10mg vs 파탁정20mg)이 여러 개 걸리면 알파벳순이라
        # "10mg"이 "20mg"보다 앞서 엉뚱한 용량이 뽑힌다. OCR이 '20mg'를 '2000'으로 읽어도 그 숫자가
        # DB 쪽 용량 숫자로 시작/포함되면 앞세운다.
        target_digits = re.search(r'\d+', normalized_key)
        if len(rows) > 1 and target_digits:
            rows.sort(key=lambda d: _dosage_rank(d, normalized_key, target_digits.group()))
        return rows

    async def _match_by_ilike(self, name: str) -> list[Drug]:
        """`item_name`/`simple_name` 부분 문자열 검색(원본 검색어 그대로). 완전일치 → 접두 → 포함 순."""
        order_expr = case(
            (Drug.simple_name.ilike(name), 0),
            (Drug.item_name.ilike(name), 1),
            (Drug.simple_name.ilike(f"{name}%"), 2),
            (Drug.item_name.ilike(f"{name}%"), 3),
            else_=4,
        )
        return list((await self.db.execute(
            select(Drug)
            .where(or_(Drug.item_name.ilike(f"%{name}%"), Drug.simple_name.ilike(f"%{name}%")))
            .order_by(order_expr, _export_last())
            .limit(5)
        )).scalars().all())

    async def _match_by_ingredient(self, name: str) -> list[Drug]:
        """성분명 기반 매칭 — 브랜드명이 성분명을 괄호 안에 숨겨('쿠파린정(와파린나트륨)') 앞 단계가
        모두 실패하는 '성분명+제형' 입력('와파린정')을 위한 최후 수단.
        짧은 이름일수록 복합제보다 단일 성분 일반의약품일 가능성이 높아 우선한다
        ('메트포르민' 검색 시 콤보약보다 '유한메트포르민서방정500mg'을 먼저)."""
        stem = _extract_ingredient_stem(name)
        if len(stem) < 2:
            return []
        return list((await self.db.execute(
            select(Drug)
            .where(_ingredient_match_clause(stem))
            .order_by(func.length(Drug.item_name), Drug.item_name)
            .limit(5)
        )).scalars().all())

    async def match_names(self, names: list[str]) -> list[dict]:
        """약품명 각각을 접두(용량 제거) → ILIKE → 성분명 순으로 찾고, 모두 빈손일 때만 유사도 후보를 낸다.

        유사도(OCR 오인식 보정: '신플렉스'↔'신플랙스')는 틀린 약이 복약함에 들어가지 않도록 `matched`로
        올리지 않고 `alternatives`(앱의 "유사 약품" 목록)로만 내려 사용자가 직접 고르게 한다.
        틀린 글자를 사전으로 고치는 게 아니라 DB 이름과의 트라이그램 유사도라 새 약이 나와도 코드 수정이 필요 없다."""
        results = []
        for name in names:
            key = _make_drug_key(name)
            rows = (
                await self._match_by_prefix(key)
                or await self._match_by_ilike(name)
                or await self._match_by_ingredient(name)
            )
            prefix = _name_prefix(key)
            fuzzy: list[Drug] = []
            if not rows:
                # 자모 한두 개 오인식('액티폐린정'→액티페린정)을 먼저, 모자라면 트라이그램 유사도로 채운다.
                fuzzy = await self._slip_candidates(key)
                if len(fuzzy) < 3:
                    seen_ids = {d.id for d in fuzzy}
                    fuzzy += [d for d in await self._fuzzy_candidates(prefix if len(prefix) >= 3 else key)
                              if d.id not in seen_ids]
                fuzzy = fuzzy[:3]
            results.append({
                "queried_name": name,
                "matched": rows[0] if rows else None,
                "alternatives": rows[1:] if len(rows) > 1 else fuzzy,
            })
        return results

    # ------------------------------------------------------------------ #
    # 성분(ingredient) 단위 DUR 조회 — quick_check 정식 경로                 #
    # 성분코드는 모두 대표 코드로 내준다(`ingredient_alias_map`): 약의 코드도, #
    # 규칙 행의 코드도. 규칙은 같은 성분의 다른 코드에 붙은 것까지 찾는다.     #
    # ------------------------------------------------------------------ #

    async def _ingredient_aliases(self) -> dict[str, str]:
        if self._aliases is None:
            name = func.replace(DurIngredientMaster.ingr_kor, " ", "")
            shared = (
                select(name.label("name"), DurIngredientMaster.mix_type)
                .group_by(name, DurIngredientMaster.mix_type)
                .having(func.count(DurIngredientMaster.ingr_code.distinct()) > 1)
                .subquery()
            )
            stmt = select(
                DurIngredientMaster.ingr_code, DurIngredientMaster.ingr_kor, DurIngredientMaster.mix_type
            ).join(shared, (name == shared.c.name) & DurIngredientMaster.mix_type.is_not_distinct_from(shared.c.mix_type))
            self._aliases = ingredient_alias_map((await self.db.execute(stmt)).tuples().all())
        return self._aliases

    async def _with_aliases(self, codes: set[str]) -> tuple[set[str], dict[str, str]]:
        """대표 코드 집합 → (같은 성분의 다른 코드까지 넣은 조회용 집합, 코드 → 대표 코드)."""
        aliases = await self._ingredient_aliases()
        return codes | {c for c, rep in aliases.items() if rep in codes}, aliases

    async def get_ingredient_codes_for_drug_list(
        self, drug_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, set[str]]:
        """약품 ID → 그 약품에 매핑된 DUR 성분코드(INGR_CODE, 대표 코드) 집합."""
        stmt = select(DrugIngredient.drug_id, DrugIngredient.ingr_code).where(
            DrugIngredient.drug_id.in_(drug_ids),
            DrugIngredient.ingr_code.isnot(None),
        )
        result = await self.db.execute(stmt)
        aliases = await self._ingredient_aliases()
        mapping: dict[uuid.UUID, set[str]] = {}
        for drug_id, ingr_code in result.all():
            mapping.setdefault(drug_id, set()).add(aliases.get(ingr_code, ingr_code))
        return mapping

    async def get_ingredient_amounts_for_drug_list(
        self, drug_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float]]:
        """약품 ID → {성분코드: 정·캡슐 1개당 mg}. 함량을 아는 성분만 담는다(용량주의 판정용)."""
        if not drug_ids:
            return {}
        stmt = select(DrugIngredient.drug_id, DrugIngredient.ingr_code, DrugIngredient.amount_mg).where(
            DrugIngredient.drug_id.in_(drug_ids),
            DrugIngredient.ingr_code.isnot(None),
            DrugIngredient.amount_mg.isnot(None),
        )
        aliases = await self._ingredient_aliases()
        mapping: dict[uuid.UUID, dict[str, float]] = {}
        for drug_id, code, amount in (await self.db.execute(stmt)).all():
            mapping.setdefault(drug_id, {}).setdefault(aliases.get(code, code), amount)
        return mapping

    async def get_hira_form_names(self, item_seqs: set[str]) -> dict[str, set[str]]:
        """품목기준코드 → 심평원 제형명들. 용량주의 규칙의 제형을 약에 맞출 때 쓴다(함량과 같은 일반명코드에서 온다)."""
        if not item_seqs:
            return {}
        stmt = (
            select(HiraItemGenCode.item_seq, HiraGenCode.form_name)
            .join(HiraGenCode, HiraGenCode.gen_code == HiraItemGenCode.gen_code)
            .where(HiraItemGenCode.item_seq.in_(item_seqs))
        )
        forms: dict[str, set[str]] = {}
        for item_seq, form in (await self.db.execute(stmt)).all():
            if form:
                forms.setdefault(item_seq, set()).add(form)
        return forms

    async def get_ingr_dose_cautions_for_codes(self, codes: set[str]) -> list[DurIngredientDoseCaution]:
        """주어진 성분코드의 용량주의 규칙 중 하루 최대량을 읽은 것."""
        if not codes:
            return []
        lookup, aliases = await self._with_aliases(codes)
        stmt = select(DurIngredientDoseCaution).where(
            DurIngredientDoseCaution.ingr_code.in_(lookup),
            DurIngredientDoseCaution.limits_mg.isnot(None),
        )
        rules = []
        for rule in (await self.db.execute(stmt)).scalars().all():
            code = aliases.get(rule.ingr_code, rule.ingr_code)
            mix = ",".join(aliases.get(c, c) for c in rule.mix_codes.split(",")) if rule.mix_codes else ""
            limits = {aliases.get(c, c): mg for c, mg in (rule.limits_mg or {}).items()}
            changed = (code, mix, limits) != (rule.ingr_code, rule.mix_codes, rule.limits_mg)
            rules.append(_recoded(rule, ingr_code=code, mix_codes=mix, limits_mg=limits) if changed else rule)
        return rules

    async def get_ingredient_kor_for_codes(self, codes: set[str]) -> dict[str, str]:
        """성분코드 → 성분 한글명."""
        if not codes:
            return {}
        lookup, aliases = await self._with_aliases(codes)
        stmt = select(DrugIngredient.ingr_code, DrugIngredient.ingr_kor).where(
            DrugIngredient.ingr_code.in_(lookup), DrugIngredient.ingr_kor.isnot(None)
        )
        result = await self.db.execute(stmt)
        return {aliases.get(code, code): kor for code, kor in result.all()}

    async def get_ingr_contraindications_for_codes(
        self, codes: set[str]
    ) -> list[DurIngredientContraindication]:
        """주어진 성분코드 집합 안에서 양쪽이 모두 매칭되는 병용금기 규칙."""
        if not codes:
            return []
        lookup, aliases = await self._with_aliases(codes)
        stmt = select(DurIngredientContraindication).where(
            DurIngredientContraindication.ingr_code_a.in_(lookup),
            DurIngredientContraindication.ingr_code_b.in_(lookup),
        )
        rules = []
        for rule in (await self.db.execute(stmt)).scalars().all():
            a, b = (aliases.get(c, c) for c in (rule.ingr_code_a, rule.ingr_code_b))
            if a == b:
                continue
            changes = {}
            if a != rule.ingr_code_a:
                changes["ingr_code_a"] = a
            if b != rule.ingr_code_b:
                changes["ingr_code_b"] = b
            rules.append(_recoded(rule, **changes))
        return rules

    async def get_ingr_effect_groups_for_codes(
        self, codes: set[str]
    ) -> list[DurIngredientEffectGroup]:
        """주어진 성분코드가 속한 DUR 효능군·계열 멤버십."""
        if not codes:
            return []
        lookup, aliases = await self._with_aliases(codes)
        stmt = select(DurIngredientEffectGroup).where(
            DurIngredientEffectGroup.ingr_code.in_(lookup)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [_recoded(row, **_canonical_code(row.ingr_code, aliases)) for row in rows]

    async def get_pregnancy_taboo_for_item_seqs(
        self, item_seqs: set[str]
    ) -> list[DurItemPregnancyTaboo]:
        """주어진 품목(ITEM_SEQ)에 걸린 DUR 임부금기 — 품목 단위라 성분코드 해소와 무관하다."""
        if not item_seqs:
            return []
        stmt = select(DurItemPregnancyTaboo).where(DurItemPregnancyTaboo.item_seq.in_(item_seqs))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_ingr_age_caution_for_codes(
        self, codes: set[str]
    ) -> list[DurIngredientAgeCaution]:
        """주어진 성분코드에 걸린 특정연령대금기(age_taboo)·노인주의(elderly_caution) 규칙."""
        if not codes:
            return []
        lookup, aliases = await self._with_aliases(codes)
        stmt = select(DurIngredientAgeCaution).where(
            DurIngredientAgeCaution.ingr_code.in_(lookup)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [_recoded(row, **_canonical_code(row.ingr_code, aliases)) for row in rows]

    # ------------------------------------------------------------------ #
    # 알레르기 규칙 기반 검사용 — 성분 한글명 조회                            #
    # ------------------------------------------------------------------ #

    async def get_ingredient_names_for_drug_list(
        self, drug_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, set[str]]:
        """약품 ID → 성분 한글명 집합. `drug_ingredients`(61% 해소)를 1차로 쓰고,
        미해소 약은 `drugs.ingr_name` JSONB(`main_item_ingr` 파싱본)로 보강한다.
        DUR 성분코드 유무와 무관하게 이름만 필요한 알레르기 대조용이라 두 소스를
        합쳐 커버리지를 최대화한다."""
        mapping: dict[uuid.UUID, set[str]] = {}
        stmt = select(DrugIngredient.drug_id, DrugIngredient.ingr_kor).where(
            DrugIngredient.drug_id.in_(drug_ids),
            DrugIngredient.ingr_kor.isnot(None),
        )
        result = await self.db.execute(stmt)
        for drug_id, ingr_kor in result.all():
            mapping.setdefault(drug_id, set()).add(ingr_kor)

        unresolved = [d for d in drug_ids if d not in mapping]
        if unresolved:
            stmt2 = select(Drug.id, Drug.ingr_name).where(
                Drug.id.in_(unresolved), Drug.ingr_name.isnot(None)
            )
            result2 = await self.db.execute(stmt2)
            for drug_id, ingr_name in result2.all():
                for elem in ingr_name or []:
                    kor = (elem or {}).get("kor")
                    if kor:
                        mapping.setdefault(drug_id, set()).add(kor)
        return mapping
