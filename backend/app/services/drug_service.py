import re
import uuid

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.models.dur_ingredient_rule import (
    DurIngredientAgeCaution,
    DurIngredientContraindication,
    DurIngredientEffectGroup,
)
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


class DrugService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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

    async def match_names(self, names: list[str]) -> list[dict]:
        """약품명 리스트 각각을 drug_key → 용량 제거 prefix → ILIKE → 성분명 순으로 검색."""
        results = []
        for name in names:
            normalized_key = _make_drug_key(name)

            # 1순위: 용량 제거 — 첫 숫자 앞까지 잘라서 prefix 검색
            # 예: '가스핀정5mg' → '가스핀정', '이미그란정50mg' → '이미그란정'
            name_prefix = re.split(r'\d', normalized_key)[0]
            name_digits_match = re.search(r'\d+', normalized_key)
            name_digits = name_digits_match.group() if name_digits_match else None
            rows = []
            if len(name_prefix) >= 2:
                order_expr = case(
                    (Drug.drug_key == normalized_key, 0),
                    else_=1,
                )
                rows = list((await self.db.execute(
                    select(Drug)
                    .where(Drug.drug_key.startswith(name_prefix))
                    .order_by(order_expr, Drug.drug_key)
                    .limit(5)
                )).scalars().all())
                # 같은 이름에 용량만 다른 제품(파탁정10mg vs 파탁정20mg)이 여러 개 걸리면,
                # 위 order_expr(완전일치 아니면 전부 동률)은 그냥 drug_key 알파벳순이라
                # "10mg"이 "20mg"보다 앞서 나와 엉뚱한 용량이 뽑히는 문제가 있었다
                # (실측 2026-09-16: OCR이 '20mg'를 '2000'으로 긁어도, 그 숫자가 DB
                # 쪽 용량 숫자로 시작/포함되면 우선한다).
                if len(rows) > 1 and name_digits:
                    def _dosage_rank(drug: Drug) -> int:
                        if drug.drug_key == normalized_key:
                            return 0
                        key_digits_match = re.search(r'\d+', drug.drug_key)
                        key_digits = key_digits_match.group() if key_digits_match else None
                        if key_digits and (
                            name_digits.startswith(key_digits) or key_digits.startswith(name_digits)
                        ):
                            return 1
                        return 2
                    rows.sort(key=_dosage_rank)

            # 2순위: drug_key 정규화 완전 일치 (용량 없는 OCR 입력 대비)
            if not rows:
                rows = list((await self.db.execute(
                    select(Drug).where(Drug.drug_key == normalized_key).limit(5)
                )).scalars().all())

            # 3순위: item_name / simple_name ILIKE 폴백 (원본 검색어 그대로 — 정밀 매칭)
            if not rows:
                order_expr = case(
                    (Drug.simple_name.ilike(name), 0),
                    (Drug.item_name.ilike(name), 1),
                    (Drug.simple_name.ilike(f"{name}%"), 2),
                    (Drug.item_name.ilike(f"{name}%"), 3),
                    else_=4,
                )
                rows = list((await self.db.execute(
                    select(Drug)
                    .where(or_(
                        Drug.item_name.ilike(f"%{name}%"),
                        Drug.simple_name.ilike(f"%{name}%"),
                    ))
                    .order_by(order_expr)
                    .limit(5)
                )).scalars().all())

            # 4순위(최후 폴백): 성분명 기반 매칭 — 브랜드명이 성분명을 괄호 안에 숨겨서
            # ('쿠파린정(와파린나트륨)') 위 3단계가 모두 실패하는 '성분명+제형' 입력 대응
            # 예: '와파린정' → 성분 '와파린나트륨'을 포함하는 제품.
            # 앞선 정밀 매칭이 하나도 없을 때만 시도하는 최후 수단이라 순서를 가장 뒤에 둔다.
            if not rows:
                stem = _extract_ingredient_stem(name)
                if len(stem) >= 2:
                    # 짧은 이름일수록 복합제보다 단일 성분 일반의약품일 가능성이 높아 우선한다
                    # (예: '메트포르민' 검색 시 콤보약 '가드메트정100/1000밀리그램(아나글립틴,메트포르민)'
                    # 보다 '유한메트포르민서방정500mg'을 먼저 보여줌).
                    rows = list((await self.db.execute(
                        select(Drug)
                        .where(_ingredient_match_clause(stem))
                        .order_by(func.length(Drug.item_name), Drug.item_name)
                        .limit(5)
                    )).scalars().all())

            matched = rows[0] if rows else None
            alternatives = rows[1:] if len(rows) > 1 else []
            results.append({
                "queried_name": name,
                "matched": matched,
                "alternatives": alternatives,
            })
        return results

    # ------------------------------------------------------------------ #
    # 성분(ingredient) 단위 DUR 조회 — quick_check 정식 경로                 #
    # ------------------------------------------------------------------ #

    async def get_ingredient_codes_for_drug_list(
        self, drug_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, set[str]]:
        """약품 ID → 그 약품에 매핑된 DUR 성분코드(INGR_CODE) 집합."""
        stmt = select(DrugIngredient.drug_id, DrugIngredient.ingr_code).where(
            DrugIngredient.drug_id.in_(drug_ids),
            DrugIngredient.ingr_code.isnot(None),
        )
        result = await self.db.execute(stmt)
        mapping: dict[uuid.UUID, set[str]] = {}
        for drug_id, ingr_code in result.all():
            mapping.setdefault(drug_id, set()).add(ingr_code)
        return mapping

    async def get_ingr_contraindications_for_codes(
        self, codes: set[str]
    ) -> list[DurIngredientContraindication]:
        """주어진 성분코드 집합 안에서 양쪽이 모두 매칭되는 병용금기 규칙."""
        if not codes:
            return []
        stmt = select(DurIngredientContraindication).where(
            DurIngredientContraindication.ingr_code_a.in_(codes),
            DurIngredientContraindication.ingr_code_b.in_(codes),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_ingr_effect_groups_for_codes(
        self, codes: set[str]
    ) -> list[DurIngredientEffectGroup]:
        """주어진 성분코드가 속한 DUR 효능군(dur_seq) 멤버십."""
        if not codes:
            return []
        stmt = select(DurIngredientEffectGroup).where(
            DurIngredientEffectGroup.ingr_code.in_(codes)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_ingr_age_caution_for_codes(
        self, codes: set[str]
    ) -> list[DurIngredientAgeCaution]:
        """주어진 성분코드에 걸린 특정연령대금기(age_taboo)·노인주의(elderly_caution) 규칙."""
        if not codes:
            return []
        stmt = select(DurIngredientAgeCaution).where(
            DurIngredientAgeCaution.ingr_code.in_(codes)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

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
