"""일회성 로컬 보강 배치 — 공공데이터 API를 새로 호출하지 않고 이미 적재된
데이터끼리 대조해 채운다."""
import json
from pathlib import Path

from sqlalchemy import select

from app.core.logging import logger
from app.models.drug import Drug
from app.models.drug_ingredient import DrugIngredient
from app.models.dur_ingredient_master import DurIngredientMaster
from app.models.hira import HiraGenIngredient, HiraItemGenCode
from app.models.residual_interaction import ResidualInteraction

from .base import _SyncBase
from .helpers import (
    _make_simple_name,
    _parse_main_ingr,
    candidate_ingredient_names,
    make_ingredient_resolver,
    resolve_hira_components,
)


class MaintenanceMixin(_SyncBase):
    async def fill_simple_names(self) -> int:
        rows = await self.db.execute(select(Drug).where(Drug.simple_name.is_(None)))
        drugs = rows.scalars().all()
        count = 0
        for drug in drugs:
            drug.simple_name = _make_simple_name(drug.item_name)
            count += 1
        await self.db.commit()
        return count

    async def fill_ingr_from_main_ingr(self) -> int:
        rows = await self.db.execute(
            select(Drug).where(Drug.main_item_ingr.isnot(None), Drug.ingr_name.is_(None))
        )
        drugs = rows.scalars().all()
        count = 0
        for drug in drugs:
            parsed = _parse_main_ingr(drug.main_item_ingr or "")
            if parsed:
                drug.ingr_name = parsed
                count += 1
        await self.db.commit()
        return count

    async def build_drug_ingredients_from_jsonb(self) -> int:
        """API 미사용 로컬 폴백 — DUR sweep이 채운 `drug_ingredients`(source='dur')에서
        `{정규화 성분명: ingr_code}` 사전을 만들고, `drug_ingredients` 행이 없는 약품의
        성분명 후보를 이름으로 매칭해 보강한다 (source='jsonb_fallback').

        성분명 후보는 세 군데서 모은다:
          1. `ingr_name` JSONB의 kor
          2. `main_item_ingr`의 `[Mxxxx]성분명` 파싱 결과
          3. `item_name` 괄호 안 텍스트 — 외용제(겔·플라스타 등)는 식약처가 DUR 성분코드를
             안 붙여 병용금기 원본에 INGR_CODE가 NULL로 오는 경우가 많은데, 제품명
             '뉴펜겔(케토프로펜)'처럼 괄호에 성분명이 노출된다.
        완전 매칭 → 접두(염 형태) 매칭 순.
        """
        rows = await self.db.execute(
            select(DrugIngredient.ingr_kor, DrugIngredient.ingr_code)
            .where(DrugIngredient.ingr_code.isnot(None), DrugIngredient.ingr_kor.isnot(None))
        )
        pairs = rows.all()
        if not pairs:
            return 0
        _resolve = make_ingredient_resolver(pairs)

        covered = set(
            (await self.db.execute(select(DrugIngredient.drug_id).distinct())).scalars().all()
        )
        drug_rows = await self.db.execute(
            select(Drug.id, Drug.item_name, Drug.ingr_name, Drug.main_item_ingr)
        )

        count = 0
        for drug_id, item_name, ingr_name, main_item_ingr in drug_rows.all():
            if drug_id in covered:
                continue

            candidates = candidate_ingredient_names(ingr_name, main_item_ingr, item_name)

            seen_codes: set[str] = set()
            for cand in candidates:
                code = _resolve(cand)
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                self.db.add(DrugIngredient(
                    drug_id=drug_id, ingr_code=code, ingr_kor=cand, source="jsonb_fallback",
                ))
                count += 1
            if count and count % 2000 == 0:
                await self.db.commit()
        await self.db.commit()
        return count

    async def build_drug_ingredients_from_hira(self) -> int:
        """성분코드가 없는 약을 심평원 약가마스터로 해소한다 (source='hira_eng', API 미사용).

        `drugs.item_seq` → 심평원 품목기준코드 → 일반명코드 → 영문 일반명 → DUR 성분정보의 영문명
        (`dur_ingredient_master.ingr_eng_norm`) 완전 일치 → 성분코드. 일반명코드는 판매 중인 포장의 것을
        먼저 쓰고, 다 취소된 품목이면 취소된 것을 쓴다. 일반명코드가 여럿인데 가리키는 성분이 서로 다르면 맺지 않는다.
        실측(2026-11-02): 기존 해소 약에 같은 규칙을 돌려 1단계 84%·2단계 92%가 기존 성분코드와 같았고(나머지 대부분은
        기존 쪽이 복합제 성분 일부를 빠뜨린 경우), 새로 맺어진 약 무작위 100건에 오매칭 0건.
        이미 성분코드가 있는 약은 건드리지 않는다. 몇 개 약을 해소했는지 돌려준다."""
        by_eng: dict[str, set[str]] = {}
        mix_type: dict[str, str | None] = {}
        kor: dict[str, str | None] = {}
        for code, ingr_kor, eng_norm, mt in (await self.db.execute(select(
            DurIngredientMaster.ingr_code, DurIngredientMaster.ingr_kor,
            DurIngredientMaster.ingr_eng_norm, DurIngredientMaster.mix_type,
        ))).all():
            if eng_norm:
                by_eng.setdefault(eng_norm, set()).add(code)
            mix_type[code] = mt
            kor.setdefault(code, ingr_kor)
        if not by_eng:
            return 0

        names: dict[str, list[str]] = {}
        for gen, name in (await self.db.execute(
            select(HiraGenIngredient.gen_code, HiraGenIngredient.ingr_name)
            .order_by(HiraGenIngredient.gen_code, HiraGenIngredient.seq)
        )).all():
            names.setdefault(gen, []).append(name)
        live: dict[str, set[str]] = {}
        cancelled: dict[str, set[str]] = {}
        for seq, gen, cancelled_on in (await self.db.execute(select(
            HiraItemGenCode.item_seq, HiraItemGenCode.gen_code, HiraItemGenCode.cancelled_on,
        ))).all():
            (cancelled if cancelled_on else live).setdefault(seq, set()).add(gen)

        covered = set((await self.db.execute(select(DrugIngredient.drug_id).distinct())).scalars().all())
        resolved = 0
        for drug_id, item_seq in (await self.db.execute(select(Drug.id, Drug.item_seq))).all():
            if drug_id in covered:
                continue
            gens = live.get(item_seq) or cancelled.get(item_seq)
            if not gens or any(g not in names for g in gens):
                continue
            results = [resolve_hira_components(names[g], by_eng, mix_type) for g in sorted(gens)]
            if any(r is None for r in results) or len({frozenset(r[0]) for r in results if r}) != 1:
                continue
            codes = results[0][0] if results[0] else set()
            for code in sorted(codes):
                self.db.add(DrugIngredient(drug_id=drug_id, ingr_code=code, ingr_kor=kor.get(code), source="hira_eng"))
            resolved += 1
            if resolved % 2000 == 0:
                await self.db.commit()
        await self.db.commit()
        return resolved

    SEED_RESIDUAL_PATH = Path(__file__).resolve().parents[3] / "seed" / "residual_interactions.json"

    async def build_residual_from_seed(self) -> int:
        """`seed/residual_interactions.json`(item_seq 쌍 기준)에서 `residual_interactions`를
        채운다. 마이그레이션 0006이 구 품목 테이블에서 뽑아 넣지만, DB를 완전 초기화
        (`down -v`)하면 그 테이블이 빈 채로 드롭돼 잔여 폴백이 사라진다 — 그 경우
        `sync.py build_residual`로 이 시드에서 복원한다. UUID가 초기화마다 바뀌므로
        `item_seq`로 저장하고 로드 시 `drug_id`로 해소한다. 재실행 안전(이미 있으면 skip).
        """
        entries = json.loads(self.SEED_RESIDUAL_PATH.read_text(encoding="utf-8"))

        # item_seq → drug_id, 기존 쌍 집합을 각각 쿼리 1번으로 미리 로드 (N+1 방지)
        seqs = {seed_row["seq1"] for seed_row in entries} | {seed_row["seq2"] for seed_row in entries}
        seq_to_id = {
            seq: drug_id
            for seq, drug_id in (await self.db.execute(
                select(Drug.item_seq, Drug.id).where(Drug.item_seq.in_(seqs))
            )).all()
        }
        existing = {
            (frozenset((r.drug1_id, r.drug2_id)), r.interaction_type)
            for r in (await self.db.execute(
                select(
                    ResidualInteraction.drug1_id,
                    ResidualInteraction.drug2_id,
                    ResidualInteraction.interaction_type,
                )
            )).all()
        }

        count = skipped = missing = 0
        for seed_row in entries:
            id1, id2 = seq_to_id.get(seed_row["seq1"]), seq_to_id.get(seed_row["seq2"])
            if not id1 or not id2:
                missing += 1
                continue
            if (frozenset((id1, id2)), seed_row["type"]) in existing:
                skipped += 1
                continue
            self.db.add(ResidualInteraction(
                drug1_id=id1, drug2_id=id2,
                interaction_type=seed_row["type"], mechanism=seed_row.get("mechanism"),
            ))
            count += 1
        await self.db.commit()
        logger.info(
            f"residual 시드 로드: {count}건 추가 / {skipped}건 기존 / {missing}건 약품 미발견"
        )
        return count
