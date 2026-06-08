import uuid

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.drug import Drug
from app.models.drug_interaction import DrugInteraction
from app.services.public_data_service import _make_drug_key


class DrugService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(self, query: str, page: int = 1, limit: int = 20) -> list[Drug]:
        offset = (page - 1) * limit
        stmt = (
            select(Drug)
            .where(
                or_(
                    Drug.item_name.ilike(f"%{query}%"),
                    Drug.simple_name.ilike(f"%{query}%"),
                )
            )
            .order_by(Drug.item_name)
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, drug_id: uuid.UUID) -> Drug:
        drug = await self.db.get(Drug, drug_id)
        if not drug:
            raise NotFoundError("약품을 찾을 수 없습니다.")
        return drug

    async def get_by_item_seq(self, item_seq: str) -> Drug | None:
        return await self.db.scalar(select(Drug).where(Drug.item_seq == item_seq))

    async def get_interactions(self, drug_id: uuid.UUID) -> list[DrugInteraction]:
        stmt = select(DrugInteraction).where(
            or_(DrugInteraction.drug1_id == drug_id, DrugInteraction.drug2_id == drug_id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_drugs_by_ids(self, drug_ids: list[uuid.UUID]) -> dict[uuid.UUID, Drug]:
        stmt = select(Drug).where(Drug.id.in_(drug_ids))
        result = await self.db.execute(stmt)
        return {d.id: d for d in result.scalars().all()}

    async def get_interactions_for_drug_list(
        self, drug_ids: list[uuid.UUID]
    ) -> list[DrugInteraction]:
        """주어진 약품 ID 목록 내 모든 쌍의 상호작용을 단일 쿼리로 조회."""
        stmt = select(DrugInteraction).where(
            DrugInteraction.drug1_id.in_(drug_ids),
            DrugInteraction.drug2_id.in_(drug_ids),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def match_names(self, names: list[str]) -> list[dict]:
        """약품명 리스트 각각을 drug_key → 용량 제거 prefix → ILIKE 순으로 검색."""
        results = []
        for name in names:
            normalized_key = _make_drug_key(name)

            # 1순위: 용량 제거 — 첫 숫자 앞까지 잘라서 prefix 검색
            # 예: '가스핀정5mg' → '가스핀정', '이미그란정50mg' → '이미그란정'
            import re as _re
            name_prefix = _re.split(r'\d', normalized_key)[0]
            rows = []
            if len(name_prefix) >= 2:
                rows = list((await self.db.execute(
                    select(Drug)
                    .where(Drug.drug_key.startswith(name_prefix))
                    .order_by(Drug.drug_key)
                    .limit(5)
                )).scalars().all())

            # 2순위: drug_key 정규화 완전 일치 (용량 없는 OCR 입력 대비)
            if not rows:
                rows = list((await self.db.execute(
                    select(Drug).where(Drug.drug_key == normalized_key).limit(5)
                )).scalars().all())

            # 3순위: item_name / simple_name ILIKE 폴백
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

            matched = rows[0] if rows else None
            alternatives = rows[1:] if len(rows) > 1 else []
            results.append({
                "queried_name": name,
                "matched": matched,
                "alternatives": alternatives,
            })
        return results

    async def get_interactions_for_pair(
        self, drug1_id: uuid.UUID, drug2_id: uuid.UUID
    ) -> list[DrugInteraction]:
        stmt = select(DrugInteraction).where(
            or_(
                (DrugInteraction.drug1_id == drug1_id) & (DrugInteraction.drug2_id == drug2_id),
                (DrugInteraction.drug1_id == drug2_id) & (DrugInteraction.drug2_id == drug1_id),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
