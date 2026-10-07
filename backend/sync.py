"""
공공데이터 동기화 CLI

사용법:
    docker exec -it drugtest-backend-1 python sync.py [명령]

명령:
    status                  현재 DB 적재 현황 출력
    overview                e약은요 기본정보 동기화
    dur_contraindications   DUR 병용금기 동기화 (성분 테이블만 채움)
    efcy_dplct              DUR 효능군중복주의 동기화 (성분 테이블만 채움)
    approval                의약품 허가정보 동기화
    build_drug_ingredients  drug_ingredients 로컬 보강 (API 미사용, item_name·ingr_name → 성분코드)
    build_residual          residual_interactions 시드 복원 (DB 완전 초기화 후 재구축 시)
    extract_risk_tags       prohibit_content → 로컬 LLM 위험/증상 태그 1회 추출 (GPU 필요)
    dur_extra_codes         DUR 기타 엔드포인트(임부/용량/투여기간)에서 성분코드 매핑만 수확
    dur_age_caution         DUR 특정연령대금기·노인주의 동기화 (성분 테이블만 채움)
    all                     overview·dur_contraindications·efcy_dplct·approval 순 (기본값)

옵션:
    --replay[=YYYYMMDD]     API를 부르지 않고 저장해 둔 원본 응답(raw)으로 재파싱·재적재.
                            날짜 생략 시 엔드포인트별 가장 최근 스냅샷. 원본은 동기화 때마다
                            SYNC_STATE_DIR/raw/ 에 자동 보관된다(최근 RAW_KEEP_SNAPSHOTS개 유지).
                            dur_contraindications는 남아 있는 체크포인트가 있으면 그 페이지부터 읽는다.

판정은 성분 단위(drug_ingredients + dur_ingredient_*)만 쓴다. dur_contraindications·
efcy_dplct 동기화가 이 테이블들을 채운다. dur_extra_codes는 판정엔 미관여하고
성분코드 해소율만 높인다. 구 품목 테이블(drug_interactions/drug_effect_groups)은
0006 마이그레이션에서 residual_interactions로 축소·폐기됨.
"""
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

os.environ.setdefault("DEBUG", "false")
os.environ["DEBUG"] = "false"

logging.basicConfig(format="%(message)s", level=logging.WARNING)
for _logger in ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects", "app"):
    logging.getLogger(_logger).setLevel(logging.WARNING)

SOURCES = ["overview", "dur_contraindications", "efcy_dplct", "approval"]

SOURCE_LABELS = {
    "overview": "e약은요 기본정보",
    "dur_contraindications": "DUR 병용금기",
    "efcy_dplct": "DUR 효능군중복주의",
    "approval": "의약품 제품 허가정보",
    "dur_extra_codes": "DUR 기타 성분코드 매핑",
    "dur_age_caution": "DUR 특정연령대금기·노인주의",
}


def _state_file() -> str:
    from app.config import settings
    return os.path.join(settings.SYNC_STATE_DIR, "last_sync.json")


def _load_state() -> dict:
    try:
        with open(_state_file(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _record_success(source: str, count: int, elapsed: float) -> None:
    """소스별 마지막 **성공** 시각·건수를 남긴다 — 데이터가 얼마나 오래됐는지 알 수 있게.
    (금기 규칙이 오래되면 새로 지정된 병용금기를 못 잡는다.)"""
    state = _load_state()
    state[source] = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": count,
        "seconds": round(elapsed, 1),
    }
    try:
        os.makedirs(os.path.dirname(_state_file()), exist_ok=True)
        with open(_state_file(), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"  (경고) 마지막 동기화 기록 저장 실패: {e}")


async def cmd_fill_ingr():
    from app.db.session import AsyncSessionLocal
    from app.services.public_data_service import PublicDataService
    print("[시작] main_item_ingr → ingr_name 일괄 채우기")
    async with AsyncSessionLocal() as db:
        svc = PublicDataService(db)
        n = await svc.fill_ingr_from_main_ingr()
    print(f"[완료] {n:,}건 업데이트")


async def cmd_build_drug_ingredients():
    from app.db.session import AsyncSessionLocal
    from app.services.public_data_service import PublicDataService
    print("[시작] drug_ingredients 로컬 보강 (ingr_name JSONB → 성분코드 이름 매칭)")
    async with AsyncSessionLocal() as db:
        svc = PublicDataService(db)
        n = await svc.build_drug_ingredients_from_jsonb()
    print(f"[완료] {n:,}건 추가 (source='jsonb_fallback')")


async def cmd_build_residual():
    from app.db.session import AsyncSessionLocal
    from app.services.public_data_service import PublicDataService
    print("[시작] residual_interactions 시드 복원 (seed/residual_interactions.json)")
    async with AsyncSessionLocal() as db:
        svc = PublicDataService(db)
        n = await svc.build_residual_from_seed()
    print(f"[완료] {n:,}건 추가")


async def cmd_extract_risk_tags():
    from app.db.session import AsyncSessionLocal
    from app.services.public_data_service import PublicDataService
    print("[시작] risk_tags 추출 (prohibit_content → 로컬 LLM, distinct만)")
    async with AsyncSessionLocal() as db:
        svc = PublicDataService(db)
        n = await svc.extract_risk_tags()
    print(f"[완료] {n:,}개 distinct 문장 태그화")




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
    from sqlalchemy import func, select

    from app.db.session import AsyncSessionLocal
    from app.models.drug import Drug
    from app.models.drug_ingredient import DrugIngredient
    from app.models.dur_ingredient_rule import (
        DurIngredientAgeCaution,
        DurIngredientContraindication,
        DurIngredientEffectGroup,
    )
    from app.models.residual_interaction import ResidualInteraction

    async with AsyncSessionLocal() as db:
        total = await db.scalar(select(func.count()).select_from(Drug))
        has_efcy = await db.scalar(select(func.count()).select_from(Drug).where(Drug.efcy_qesitm.isnot(None)))
        has_ingr = await db.scalar(select(func.count()).select_from(Drug).where(Drug.ingr_name.isnot(None)))
        di_rows = await db.scalar(select(func.count()).select_from(DrugIngredient))
        di_drugs = await db.scalar(
            select(func.count(func.distinct(DrugIngredient.drug_id)))
            .where(DrugIngredient.ingr_code.isnot(None))
        )
        ingr_contra = await db.scalar(select(func.count()).select_from(DurIngredientContraindication))
        ingr_effect = await db.scalar(select(func.count()).select_from(DurIngredientEffectGroup))
        age_taboo = await db.scalar(
            select(func.count()).select_from(DurIngredientAgeCaution)
            .where(DurIngredientAgeCaution.rule_type == "age_taboo")
        )
        elderly_caution = await db.scalar(
            select(func.count()).select_from(DurIngredientAgeCaution)
            .where(DurIngredientAgeCaution.rule_type == "elderly_caution")
        )
        residual = await db.scalar(select(func.count()).select_from(ResidualInteraction))

    resolve_pct = ((di_drugs or 0) / total * 100) if total else 0

    print("\n===== 데이터 적재 현황 =====")
    print(f"  drugs 전체          : {total:>7,}건")
    print(f"  └ 효능정보(efcy)    : {has_efcy:>7,}건")
    print(f"  └ 성분JSONB(ingr)   : {has_ingr:>7,}건")
    print("  ----- 성분 단위 (정식 판정) -----")
    print(f"  drug_ingredients    : {di_rows:>7,}건")
    print(f"  └ 성분코드 해소 약품 : {di_drugs:>7,}건 ({resolve_pct:.1f}% of drugs)")
    print(f"  성분 병용금기 규칙   : {ingr_contra:>7,}건")
    print(f"  성분 효능군중복 규칙 : {ingr_effect:>7,}건")
    print(f"  특정연령대금기 규칙  : {age_taboo:>7,}건")
    print(f"  노인주의 규칙        : {elderly_caution:>7,}건")
    print(f"  residual_interactions: {residual:>6,}건 (성분코드 미해소 약 폴백)")
    state = _load_state()
    if state:
        print("  ----- 마지막 성공 동기화 (UTC) -----")
        for source, info in sorted(state.items()):
            label = SOURCE_LABELS.get(source, source)
            print(f"  {label:<22}: {info['at']}  ({info['count']:,}건)")
    else:
        print("  마지막 성공 동기화 기록 없음")
    print("============================\n")


async def run_sync(sources: list[str], replay: str | None = None) -> list[str]:
    """실패한 소스 이름 목록을 돌려준다. 이전엔 실패해도 [오류]만 찍고 종료 코드 0이라
    자동 실행(작업 스케줄러)에서 실패를 알 수 없었다."""
    from app.db.session import AsyncSessionLocal

    failed: list[str] = []
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
            service.replay_snapshot = replay

            try:
                if source == "overview":
                    n = await service._sync_drug_overview()
                elif source == "dur_contraindications":
                    n = await service._sync_dur_contraindications()
                elif source == "efcy_dplct":
                    n = await service._sync_efcy_dplct()
                elif source == "approval":
                    n = await service.sync_drug_approval()
                elif source == "dur_extra_codes":
                    n = await service.sync_dur_extra_ingredient_codes()
                elif source == "dur_age_caution":
                    n = await service.sync_dur_age_caution()
                else:
                    continue

                elapsed = time.time() - start
                print(f"\r[완료] {label}: {n:,}건  ({elapsed:.1f}초)          ")
                _record_success(source, n, elapsed)
            except Exception as e:
                print(f"\r[오류] {label}: {e}")
                failed.append(source)
    return failed


async def main_async():
    args = [a for a in sys.argv[1:] if not a.startswith("--replay")]
    replay_args = [a for a in sys.argv[1:] if a.startswith("--replay")]
    replay = None
    if replay_args:
        replay = replay_args[0].partition("=")[2] or "latest"
        print(f"[replay] API 대신 저장된 원본 응답({replay})으로 재적재합니다.")
    cmd = args[0] if args else "all"
    failed: list[str] = []

    if cmd == "status":
        await cmd_status()
    elif cmd == "fill_ingr":
        await cmd_fill_ingr()
        await cmd_status()
    elif cmd == "build_drug_ingredients":
        await cmd_build_drug_ingredients()
        await cmd_status()
    elif cmd == "build_residual":
        await cmd_build_residual()
        await cmd_status()
    elif cmd == "extract_risk_tags":
        await cmd_extract_risk_tags()
    elif cmd == "fill_simple_names":
        await cmd_fill_simple_names()
        await cmd_status()
    elif cmd == "all":
        print("전체 동기화를 시작합니다.")
        failed = await run_sync(SOURCES, replay)
        await cmd_status()
    elif cmd == "dur_extra_codes":
        failed = await run_sync(["dur_extra_codes"], replay)
        await cmd_status()
    elif cmd == "dur_age_caution":
        failed = await run_sync(["dur_age_caution"], replay)
        await cmd_status()
    elif cmd in SOURCES:
        failed = await run_sync([cmd], replay)
        await cmd_status()
    else:
        print(__doc__)
        sys.exit(1)

    if failed:
        print(f"실패한 동기화: {', '.join(failed)}")
        sys.exit(1)


def main():
    asyncio.run(main_async())


main()
