"""일회성 로컬 보강 배치 — 공공데이터 API를 새로 호출하지 않고 이미 적재된
데이터끼리 대조해 채운다."""
import json
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    hira_amount_mg,
    make_ingredient_resolver,
    resolve_hira_components,
)


async def dur_ingredient_name_pairs(db: AsyncSession) -> list[tuple[str | None, str | None]]:
    """이름으로 성분코드를 맺을 때 기준이 되는 `(성분명, 성분코드)` — DUR 성분정보 이름을 먼저, DUR 품목정보가 준 이름을 다음에.
    이름 매칭으로 맺은 행(jsonb_fallback·permit_detail)은 넣지 않는다(`make_ingredient_resolver` 참고)."""
    master = (await db.execute(select(DurIngredientMaster.ingr_kor, DurIngredientMaster.ingr_code))).all()
    dur = (await db.execute(
        select(DrugIngredient.ingr_kor, DrugIngredient.ingr_code).distinct()
        .where(DrugIngredient.source == "dur", DrugIngredient.ingr_code.isnot(None), DrugIngredient.ingr_kor.isnot(None))
    )).all()
    return [(r[0], r[1]) for r in master] + [(r[0], r[1]) for r in dur]


def _unambiguous_codes(names: list[str], by_eng: dict[str, set[str]], mix_type: dict[str, str | None]) -> set[str]:
    """일반명코드의 성분마다 따로 맞춰, 코드가 정확히 하나로 정해지는 성분의 코드만 모은다."""
    codes: set[str] = set()
    for name in names:
        hit = resolve_hira_components([name], by_eng, mix_type)
        if hit and len(hit[0]) == 1:
            codes |= hit[0]
    return codes



def _hira_codes_to_add(
    gen_names: list[list[str]], have: set[str], by_eng: dict[str, set[str]], mix_type: dict[str, str | None],
) -> set[str]:
    """약 하나의 일반명코드별 성분 이름들 → 새로 더할 성분코드. 일반명코드끼리 가리키는 성분이 다르거나 하나라도 못 맞추면 없음.
    이미 맺힌 약은 기존 코드가 심평원 구성에 모두 들어 있을 때만, 영문명 하나가 코드 하나에만 맞는 성분을 보탠다 —
    같은 이름의 '단일' 코드가 둘인 성분(나프록센·사이클로스포린 등)은 어느 코드인지 하나로 정해지지 않아 보태지 않는다
    (같은 성분의 중복 코드다 — 판정은 `drug_service.ingredient_alias_map`으로 하나로 본다)."""
    results = [resolve_hira_components(n, by_eng, mix_type) for n in gen_names]
    if any(r is None for r in results) or len({frozenset(r[0]) for r in results if r}) != 1:
        return set()
    codes = results[0][0] if results[0] else set()
    if not have:
        return codes
    if not have <= codes:
        return set()
    return _unambiguous_codes(gen_names[0], by_eng, mix_type) - have

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
        """API 미사용 로컬 폴백 — DUR 성분정보 이름과 DUR sweep이 채운 `drug_ingredients`(source='dur')에서
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
        pairs = await dur_ingredient_name_pairs(self.db)
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
        """심평원 약가마스터로 약의 성분코드를 맺는다 (source='hira_eng', API 미사용).

        `drugs.item_seq` → 심평원 품목기준코드 → 일반명코드 → 영문 일반명 → DUR 성분정보의 영문명
        (`dur_ingredient_master.ingr_eng_norm`) 완전 일치 → 성분코드. 일반명코드는 판매 중인 포장의 것을
        먼저 쓰고, 다 취소된 품목이면 취소된 것을 쓴다. 일반명코드가 여럿인데 가리키는 성분이 서로 다르면 맺지 않는다.
        실측(2026-11-02): 기존 해소 약에 같은 규칙을 돌려 1단계 84%·2단계 92%가 기존 성분코드와 같았고(나머지 대부분은
        기존 쪽이 복합제 성분 일부를 빠뜨린 경우), 새로 맺어진 약 무작위 100건에 오매칭 0건.
        성분코드가 없는 약은 전부 맺고, 이미 일부만 맺힌 약은 **기존 코드가 심평원 구성에 모두 들어 있을 때만** 빠진 코드를 더한다
        (감기약에 아세트아미노펜이 빠진 경우). 기존 코드 중 하나라도 심평원 구성에 없으면 두 출처가 어긋난 것이라 건드리지 않는다.
        새로 맺거나 보탠 약 수를 돌려준다."""
        by_eng, mix_type, kor = await self._dur_master_index()
        if not by_eng:
            return 0

        names: dict[str, list[str]] = {}
        for gen, name in (await self.db.execute(
            select(HiraGenIngredient.gen_code, HiraGenIngredient.ingr_name)
            .order_by(HiraGenIngredient.gen_code, HiraGenIngredient.seq)
        )).all():
            names.setdefault(gen, []).append(name)
        gens_of = await self._hira_gen_codes_by_item()

        existing: dict = {}
        for drug_id, code in (await self.db.execute(select(DrugIngredient.drug_id, DrugIngredient.ingr_code))).all():
            existing.setdefault(drug_id, set()).add(code)
        resolved = 0
        for drug_id, item_seq in (await self.db.execute(select(Drug.id, Drug.item_seq))).all():
            gens = gens_of(item_seq)
            if not gens or any(g not in names for g in gens):
                continue
            to_add = _hira_codes_to_add([names[g] for g in sorted(gens)], existing.get(drug_id, set()), by_eng, mix_type)
            if not to_add:
                continue
            for code in sorted(to_add):
                self.db.add(DrugIngredient(drug_id=drug_id, ingr_code=code, ingr_kor=kor.get(code), source="hira_eng"))
            resolved += 1
            if resolved % 2000 == 0:
                await self.db.commit()
        await self.db.commit()
        return resolved

    async def _dur_master_index(
        self,
    ) -> tuple[dict[str, set[str]], dict[str, str | None], dict[str, str | None]]:
        """DUR 성분정보 조회표 → (정규화 영문명 → 성분코드들, 코드 → 단일/복합, 코드 → 한글명)."""
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
        return by_eng, mix_type, kor

    async def _hira_gen_codes_by_item(self) -> Callable[[str], set[str] | None]:
        """품목기준코드 → 일반명코드들. 판매 중인 포장의 코드를 먼저 쓰고, 다 취소된 품목이면 취소된 것을 쓴다."""
        live: dict[str, set[str]] = {}
        cancelled: dict[str, set[str]] = {}
        for seq, gen, cancelled_on in (await self.db.execute(select(
            HiraItemGenCode.item_seq, HiraItemGenCode.gen_code, HiraItemGenCode.cancelled_on,
        ))).all():
            (cancelled if cancelled_on else live).setdefault(seq, set()).add(gen)
        return lambda item_seq: live.get(item_seq) or cancelled.get(item_seq)

    async def build_drug_amounts(self) -> int:
        """내복 정·캡슐 약의 1개당 성분 함량(mg)을 심평원 주성분에서 `drug_ingredients.amount_mg`에 채운다(API 미사용).

        일반명코드의 성분마다 영문명을 DUR 성분코드로 맞추고(`resolve_hira_components`와 같은 완전 일치 규칙),
        그 약에 이미 있는 성분코드 행에만 함량을 쓴다 — 성분코드 해소는 바꾸지 않는다. 투여경로가 내복(일반명코드
        7번째 글자 'A')이 아니거나, 정·캡슐이 아니거나, 일반명코드가 여럿인데 함량이 서로 다르면 비워 둔다.
        같은 코드에 맞는 성분이 둘이면(속방·서방층 등) 더한다. 매번 전부 다시 계산한다. 함량을 채운 약 수를 돌려준다."""
        by_eng, mix_type, _ = await self._dur_master_index()
        comps: dict[str, list[tuple[str, float | None]]] = {}
        for gen, name, strength, unit, form in (await self.db.execute(select(
            HiraGenIngredient.gen_code, HiraGenIngredient.ingr_name, HiraGenIngredient.strength,
            HiraGenIngredient.unit, HiraGenIngredient.form_name,
        ))).all():
            comps.setdefault(gen, []).append((name, hira_amount_mg(strength, unit, form)))
        gens_of = await self._hira_gen_codes_by_item()

        def amounts_of(gen: str) -> dict[str, float] | None:
            if gen[6:7] != "A" or gen not in comps:
                return None
            out: dict[str, float] = {}
            for name, mg in comps[gen]:
                hit = resolve_hira_components([name], by_eng, mix_type)
                if mg is None or hit is None or len(hit[0]) != 1:
                    continue
                code = next(iter(hit[0]))
                out[code] = round(out.get(code, 0.0) + mg, 6)
            return out or None

        rows_by_drug: dict = {}  # drug_id -> {성분코드: drug_ingredients.id}
        for row_id, drug_id, code in (await self.db.execute(
            select(DrugIngredient.id, DrugIngredient.drug_id, DrugIngredient.ingr_code)
        )).all():
            rows_by_drug.setdefault(drug_id, {})[code] = row_id

        params, filled = [], set()
        for drug_id, item_seq in (await self.db.execute(select(Drug.id, Drug.item_seq))).all():
            gens = gens_of(item_seq)
            if drug_id not in rows_by_drug or not gens:
                continue
            per_gen = [amounts_of(g) for g in sorted(gens)]
            if per_gen[0] is None or any(a != per_gen[0] for a in per_gen):
                continue
            for code, mg in per_gen[0].items():
                if code in rows_by_drug[drug_id]:
                    params.append({"id": rows_by_drug[drug_id][code], "amount_mg": mg})
                    filled.add(drug_id)

        await self.db.execute(update(DrugIngredient).values(amount_mg=None))
        if params:
            await self.db.execute(update(DrugIngredient), params)  # 기본키(id)로 행마다 갱신
        await self.db.commit()
        return len(filled)

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
