"""
공공데이터 동기화 CLI

사용법:
    docker exec -it drugtest-backend-1 python sync.py [명령]

명령:
    status                  현재 DB 적재 현황 출력
    dedupe_interactions      drug_interactions 양방향 중복 쌍 정리
    overview                e약은요 기본정보 동기화
    dur_contraindications   DUR 병용금기 동기화
    efcy_dplct              DUR 효능군중복주의 동기화 (병용금기 아닌 '주의' 등급)
    dur_ingredients         DUR 성분정보 동기화
    identification          낱알식별 동기화
    approval                의약품 허가정보 동기화
    all                     위 6개 순서대로 전체 동기화 (기본값)
"""
import asyncio
import os
import sys
import time
import logging

os.environ.setdefault("DEBUG", "false")
os.environ["DEBUG"] = "false"

logging.basicConfig(format="%(message)s", level=logging.WARNING)
for _logger in ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects", "app"):
    logging.getLogger(_logger).setLevel(logging.WARNING)

SOURCES = ["overview", "dur_contraindications", "efcy_dplct", "dur_ingredients", "identification", "approval"]

SOURCE_LABELS = {
    "overview": "e약은요 기본정보",
    "dur_contraindications": "DUR 병용금기",
    "efcy_dplct": "DUR 효능군중복주의",
    "dur_ingredients": "DUR 성분정보",
    "identification": "낱알식별",
    "approval": "의약품 제품 허가정보",
}


async def cmd_fill_ingr():
    from app.db.session import AsyncSessionLocal
    from app.services.public_data_service import PublicDataService
    print("[시작] main_item_ingr → ingr_name 일괄 채우기")
    async with AsyncSessionLocal() as db:
        svc = PublicDataService(db)
        n = await svc.fill_ingr_from_main_ingr()
    print(f"[완료] {n:,}건 업데이트")


async def cmd_dedupe_interactions():
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        before = (await db.execute(text("SELECT count(*) FROM drug_interactions"))).scalar()
        result = await db.execute(text("""
            DELETE FROM drug_interactions t
            WHERE t.drug1_id > t.drug2_id
            AND EXISTS (
                SELECT 1 FROM drug_interactions m
                WHERE m.drug1_id = t.drug2_id
                  AND m.drug2_id = t.drug1_id
                  AND m.interaction_type = t.interaction_type
            )
        """))
        await db.commit()
        after = (await db.execute(text("SELECT count(*) FROM drug_interactions"))).scalar()
        print(f"[완료] drug_interactions 중복 쌍 정리: {before:,}건 → {after:,}건 ({result.rowcount:,}건 삭제)")


async def cmd_fill_simple_names():
    from app.db.session import AsyncSessionLocal
    from app.services.public_data_service import PublicDataService
    print("[시작] item_name → simple_name 일괄 채우기")
    async with AsyncSessionLocal() as db:
        svc = PublicDataService(db)
        n = await svc.fill_simple_names()
    print(f"[완료] {n:,}건 업데이트")


def _bar(count: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return f"[{'?' * width}]"
    filled = int(width * count / total)
    return f"[{'#' * filled}{'-' * (width - filled)}]"


async def cmd_status():
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import func, select
    from app.models.drug import Drug
    from app.models.drug_effect_group import DrugEffectGroup
    from app.models.drug_interaction import DrugInteraction

    async with AsyncSessionLocal() as db:
        total = await db.scalar(select(func.count()).select_from(Drug))
        has_efcy = await db.scalar(select(func.count()).select_from(Drug).where(Drug.efcy_qesitm.isnot(None)))
        has_ingr = await db.scalar(select(func.count()).select_from(Drug).where(Drug.ingr_name.isnot(None)))
        has_shape = await db.scalar(select(func.count()).select_from(Drug).where(Drug.drug_shape.isnot(None)))
        interactions = await db.scalar(select(func.count()).select_from(DrugInteraction))
        effect_groups = await db.scalar(select(func.count()).select_from(DrugEffectGroup))

    print("\n===== 데이터 적재 현황 =====")
    print(f"  drugs 전체          : {total:>7,}건")
    print(f"  └ 효능정보(efcy)    : {has_efcy:>7,}건")
    print(f"  └ 성분JSONB(ingr)   : {has_ingr:>7,}건")
    print(f"  └ 낱알식별(shape)   : {has_shape:>7,}건")
    print(f"  drug_interactions   : {interactions:>7,}건")
    print(f"  drug_effect_groups  : {effect_groups:>7,}건 (효능군중복주의)")
    print("============================\n")


async def run_sync(sources: list[str]):
    from app.db.session import AsyncSessionLocal
    from app.services.public_data_service import PublicDataService

    async with AsyncSessionLocal() as db:
        for source in sources:
            label = SOURCE_LABELS[source]
            print(f"\n[시작] {label}")
            start = time.time()

            last_data = {}

            async def _cb(data, _label=label, _last=last_data):
                _last.update(data)
                page = data.get("page", "?")
                count = data.get("count", 0)
                total = data.get("total", 0)
                bar = _bar(count, total)
                pct = f"{count / total * 100:.1f}%" if total > 0 else "..."
                print(f"\r  페이지 {page:>4}  {bar}  {count:>6}/{total:<6}  {pct}", end="", flush=True)

            service = PublicDataService(db, progress_cb=_cb)

            try:
                if source == "overview":
                    n = await service._sync_drug_overview()
                elif source == "dur_contraindications":
                    n = await service._sync_dur_contraindications()
                elif source == "efcy_dplct":
                    n = await service._sync_efcy_dplct()
                elif source == "dur_ingredients":
                    n = await service._sync_dur_ingredients()
                elif source == "identification":
                    n = await service._sync_drug_identification()
                elif source == "approval":
                    n = await service.sync_drug_approval()
                else:
                    continue

                elapsed = time.time() - start
                print(f"\r[완료] {label}: {n:,}건  ({elapsed:.1f}초)          ")
            except Exception as e:
                print(f"\r[오류] {label}: {e}")


async def main_async():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd == "status":
        await cmd_status()
    elif cmd == "dedupe_interactions":
        await cmd_dedupe_interactions()
        await cmd_status()
    elif cmd == "fill_ingr":
        await cmd_fill_ingr()
        await cmd_status()
    elif cmd == "fill_simple_names":
        await cmd_fill_simple_names()
        await cmd_status()
    elif cmd == "all":
        print("전체 동기화를 시작합니다.")
        await run_sync(SOURCES)
        await cmd_status()
    elif cmd in SOURCES:
        await run_sync([cmd])
        await cmd_status()
    else:
        print(__doc__)
        sys.exit(1)


def main():
    asyncio.run(main_async())


main()
