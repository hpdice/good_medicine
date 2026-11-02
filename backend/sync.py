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
    build_drug_ingredients_hira  drug_ingredients 심평원 경로 보강 (hira_master 적재 후, 미해소 약만, source='hira_eng')
    build_drug_amounts      drug_ingredients.amount_mg — 정·캡슐 1개당 성분 함량(심평원 주성분, 용량주의 판정용)
    build_residual          residual_interactions 시드 복원 (DB 완전 초기화 후 재구축 시)
    extract_risk_tags       prohibit_content → 로컬 LLM 위험/증상 태그 1회 추출 (GPU 필요)
    dur_age_caution        DUR 특정연령대금기·노인주의 동기화 (성분 테이블만 채움)
    dur_pregnancy           DUR 임부금기 동기화 (품목 단위 판정 규칙 + 성분코드 매핑)
    dur_ingredient          DUR 성분정보 7종 → 성분코드 조회표 + 판정 규칙 보강(품목정보에 없는 규칙을 source=ingredient로 추가)
    hira_master             심평원 약가마스터 CSV 2종(SYNC_STATE_DIR/hira/) → 품목↔일반명코드, 일반명코드 성분 구성.
                            같은 파일이면 건너뛰고, 새 파일이면 바뀐 행만 쓴다 (API 미사용)
    box_detail              복약함에 이미 담긴 약을 허가정보 상세 API로 보강 (효능·용법·주의·성분).
                            새로 담는 약은 담는 순간 자동 보강되므로, 이 기능 도입 전 항목용 1회성
    all                     overview·dur_contraindications·efcy_dplct·approval 순 (기본값)

옵션:
    --replay[=YYYYMMDD]     API를 부르지 않고 저장해 둔 원본 응답(raw)으로 재파싱·재적재.
                            날짜 생략 시 엔드포인트별 가장 최근 스냅샷. 원본은 동기화 때마다
                            SYNC_STATE_DIR/raw/ 에 자동 보관된다(최근 RAW_KEEP_SNAPSHOTS개 유지).
                            dur_contraindications는 남아 있는 체크포인트가 있으면 그 페이지부터 읽는다.
    --since=YYYYMMDD        DUR 품목정보 4종(병용금기·효능군중복·연령·임부)을 이 날짜 이후 바뀐 행만 받는다.
                            생략하면 마지막 성공 동기화 3일 전부터(기록이 없으면 전체). 이미 적재한 행은 다시 받지 않는다.
    --full                  DUR 품목정보도 전체를 받는다(병용금기는 약 7시간).

판정은 성분 단위(drug_ingredients + dur_ingredient_*)만 쓴다. dur_contraindications·
efcy_dplct 동기화가 이 테이블들을 채운다. 구 품목 테이블(drug_interactions/
drug_effect_groups)은 0006 마이그레이션에서 residual_interactions로 축소·폐기됨.
"""
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DEBUG", "false")
os.environ["DEBUG"] = "false"

logging.basicConfig(format="%(message)s", level=logging.WARNING)
for _logger in ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects", "app"):
    logging.getLogger(_logger).setLevel(logging.WARNING)

# `all`(기본값)이 도는 소스. dur_age_caution·dur_pregnancy·dur_ingredient는 이름으로만 따로 돌린다.
SOURCES = ["overview", "dur_contraindications", "efcy_dplct", "approval"]

# 소스 이름 -> (표시 이름, PublicDataService 메서드 이름)
SOURCE_OPS = {
    "overview": ("e약은요 기본정보", "_sync_drug_overview"),
    "dur_contraindications": ("DUR 병용금기", "_sync_dur_contraindications"),
    "efcy_dplct": ("DUR 효능군중복주의", "_sync_efcy_dplct"),
    "approval": ("의약품 제품 허가정보", "sync_drug_approval"),
    "dur_age_caution": ("DUR 특정연령대금기·노인주의", "sync_dur_age_caution"),
    "dur_pregnancy": ("DUR 임부금기", "sync_dur_pregnancy_taboo"),
    "dur_ingredient": ("DUR 성분정보 (조회표·판정 규칙)", "sync_dur_ingredient"),
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


# 로컬 보강 명령 (공공 API 미사용): 명령 -> (시작 문구, PublicDataService 메서드, 완료 문구, 끝나고 현황 출력 여부)
LOCAL_JOBS = {
    "fill_ingr": ("main_item_ingr → ingr_name 일괄 채우기", "fill_ingr_from_main_ingr", "{n:,}건 업데이트", True),
    "build_drug_ingredients": ("drug_ingredients 로컬 보강 (ingr_name JSONB → 성분코드 이름 매칭)", "build_drug_ingredients_from_jsonb", "{n:,}건 추가 (source='jsonb_fallback')", True),
    "build_residual": ("residual_interactions 시드 복원 (seed/residual_interactions.json)", "build_residual_from_seed", "{n:,}건 추가", True),
    "extract_risk_tags": ("risk_tags 추출 (prohibit_content → 로컬 LLM, distinct만)", "extract_risk_tags", "{n:,}개 distinct 문장 태그화", False),
    "fill_simple_names": ("item_name → simple_name 일괄 채우기", "fill_simple_names", "{n:,}건 업데이트", True),
    "build_drug_ingredients_hira": ("drug_ingredients 심평원 경로 보강 (품목→일반명코드→영문 일반명→성분코드)", "build_drug_ingredients_from_hira", "{n:,}개 약 해소 (source='hira_eng')", True),
    "build_drug_amounts": ("drug_ingredients.amount_mg 채우기 (심평원 주성분 함량, 내복 정·캡슐)", "build_drug_amounts", "{n:,}개 약 함량 채움", False),
    "hira_master": ("심평원 약가마스터 CSV 적재 (SYNC_STATE_DIR/hira/)", "load_hira_master", "{n:,}행 추가·갱신·삭제", False),
}

# 변경일(`start_change_date`)로 변경분만 받을 수 있는 DUR 품목정보 소스
CHANGE_DATE_SOURCES = {"dur_contraindications", "efcy_dplct", "dur_age_caution", "dur_pregnancy"}
CHANGE_DATE_MARGIN_DAYS = 3  # 원천의 변경일 기록이 하루 이틀 늦게 찍혀도 놓치지 않게


def _change_since(source: str, since: str | None, full: bool) -> str | None:
    """이 소스를 변경분으로 받을 기준일(YYYYMMDD). None이면 전체."""
    if source not in CHANGE_DATE_SOURCES or full:
        return None
    if since:
        return since
    last = _load_state().get(source, {}).get("at")
    if not last:
        return None
    return (datetime.fromisoformat(last) - timedelta(days=CHANGE_DATE_MARGIN_DAYS)).strftime("%Y%m%d")


async def run_local_job(start: str, method: str, done: str) -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.public_data_service import PublicDataService
    print(f"[시작] {start}")
    async with AsyncSessionLocal() as db:
        n = await getattr(PublicDataService(db), method)()
    print(f"[완료] {done.format(n=n)}")


async def cmd_box_detail() -> bool:
    """복약함에 담긴 모든 약(전 사용자, 현재·과거 항목 포함) 중 아직 보강 안 한 약을 상세 API로 채운다.
    약 ID는 payload에 암호화돼 있어 복호화해서 모은다 — 약 목록만 메모리에 잠깐 들고 있고 출력하지 않는다."""
    import uuid

    from sqlalchemy import select

    from app.core.encryption import get_encryptor
    from app.db.session import AsyncSessionLocal
    from app.models.drug import Drug
    from app.models.medicine_box import MedicineBoxEntry
    from app.services.drug_detail_service import DrugDetailService

    print("[시작] 복약함 약품 허가정보 상세 보강")
    enc = get_encryptor()
    async with AsyncSessionLocal() as db:
        drug_ids: set[uuid.UUID] = set()
        for payload in (await db.execute(select(MedicineBoxEntry.payload_encrypted))).scalars():
            try:
                drug_ids.add(uuid.UUID(enc.decrypt(payload)["drug_id"]))
            except Exception:  # noqa: BLE001 — 깨진 항목 하나가 전체를 막지 않게
                continue
        drugs = list((await db.execute(
            select(Drug).where(Drug.id.in_(drug_ids), Drug.detail_fetched_at.is_(None))
        )).scalars())
        print(f"  복약함 약품 {len(drug_ids)}종 중 미보강 {len(drugs)}종")
        svc = DrugDetailService(db)
        done = failed = 0
        for drug in drugs:
            if await svc.ensure_detail(drug):
                done += 1
            else:
                failed += 1
                print(f"  (실패) {drug.item_name} — 다음 실행에서 재시도")
    print(f"[완료] 보강 {done}종, 실패 {failed}종")
    return failed == 0


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
        DurItemPregnancyTaboo,
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
        pregnancy_items = await db.scalar(
            select(func.count(func.distinct(DurItemPregnancyTaboo.item_seq)))
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
    print(f"  임부금기 규칙(품목)  : {pregnancy_items:>7,}건")
    print(f"  residual_interactions: {residual:>6,}건 (성분코드 미해소 약 폴백)")
    state = _load_state()
    if state:
        print("  ----- 마지막 성공 동기화 (UTC) -----")
        for source, info in sorted(state.items()):
            label = SOURCE_OPS.get(source, (source, ""))[0]  # 폐기된 소스의 옛 기록은 이름 그대로
            print(f"  {label:<22}: {info['at']}  ({info['count']:,}건)")
    else:
        print("  마지막 성공 동기화 기록 없음")
    print("============================\n")


async def run_sync(
    sources: list[str], replay: str | None = None, since: str | None = None, full: bool = False,
) -> list[str]:
    """실패한 소스 이름 목록을 돌려준다. 호출부가 이 목록으로 종료 코드를 정해
    자동 실행(작업 스케줄러)에서 실패를 알 수 있게 한다."""
    from app.db.session import AsyncSessionLocal

    failed: list[str] = []
    from app.services.public_data_service import PublicDataService

    async with AsyncSessionLocal() as db:
        for source in sources:
            label, method = SOURCE_OPS[source]
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
            # replay는 저장된 페이지를 그대로 읽으므로 변경분 필터를 걸지 않는다.
            service.change_since = None if replay else _change_since(source, since, full)
            if service.change_since:
                print(f"  {service.change_since} 이후 바뀐 행만 받습니다 (전체는 --full)")

            try:
                n = await getattr(service, method)()
                elapsed = time.time() - start
                print(f"\r[완료] {label}: {n:,}건  ({elapsed:.1f}초)          ")
                _record_success(source, n, elapsed)
            except Exception as e:
                print(f"\r[오류] {label}: {e}")
                failed.append(source)
    return failed


def parse_args(argv: list[str]) -> tuple[str, str | None, str | None, bool]:
    """(명령, replay 스냅샷, 변경분 기준일, 전체 여부).
    `--replay[=YYYYMMDD]`가 없으면 replay 는 None, 날짜가 없으면 "latest"."""
    positional = [a for a in argv if not a.startswith("--")]
    replay_flags = [a for a in argv if a.startswith("--replay")]
    replay = (replay_flags[0].partition("=")[2] or "latest") if replay_flags else None
    since_flags = [a.partition("=")[2] for a in argv if a.startswith("--since=")]
    since = since_flags[0] if since_flags else None
    if since and not (len(since) == 8 and since.isdigit()):
        raise SystemExit(f"--since 형식은 YYYYMMDD: {since}")
    return (positional[0] if positional else "all"), replay, since, "--full" in argv


async def main_async():
    cmd, replay, since, full = parse_args(sys.argv[1:])
    if replay:
        print(f"[replay] API 대신 저장된 원본 응답({replay})으로 재적재합니다.")
    failed: list[str] = []

    if cmd == "status":
        await cmd_status()
    elif cmd in LOCAL_JOBS:
        start, method, done, show_status = LOCAL_JOBS[cmd]
        await run_local_job(start, method, done)
        if show_status:
            await cmd_status()
    elif cmd == "box_detail":
        if not await cmd_box_detail():
            failed = ["box_detail"]
    elif cmd == "all":
        print("전체 동기화를 시작합니다.")
        failed = await run_sync(SOURCES, replay, since, full)
        await cmd_status()
    elif cmd in SOURCE_OPS:
        failed = await run_sync([cmd], replay, since, full)
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
