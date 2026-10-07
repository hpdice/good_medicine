"""공공 API 원본 응답 보관(bronze) — 페이지 단위 gzip JSON 파일.

`<SYNC_STATE_DIR>/raw/<엔드포인트>/<YYYYMMDD>/page_000001.json.gz`. 응답 본문만 저장한다
(요청 URL의 serviceKey는 들어가지 않는다). 같은 날 같은 페이지를 다시 받으면 덮어쓴다(멱등).
저장 실패는 동기화를 막지 않는다 — 원본 보관은 부가 기능이고 판정·적재가 우선이다.
"""
import gzip
import json
import os
import shutil
from datetime import datetime

from app.config import settings
from app.core.logging import logger


def endpoint_name(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def raw_root() -> str:
    return os.path.join(settings.SYNC_STATE_DIR, "raw")


def _page_path(endpoint: str, snapshot: str, page: int) -> str:
    return os.path.join(raw_root(), endpoint, snapshot, f"page_{page:06d}.json.gz")


def today_snapshot() -> str:
    return datetime.now().strftime("%Y%m%d")


def save_page(endpoint: str, snapshot: str, page: int, data: dict) -> None:
    path = _page_path(endpoint, snapshot, page)
    new_snapshot = not os.path.isdir(os.path.dirname(path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)  # 쓰다 죽어도 깨진 파일이 page_*.json.gz로 남지 않게
    if new_snapshot:
        _prune(endpoint)


def _prune(endpoint: str) -> None:
    base = os.path.join(raw_root(), endpoint)
    snapshots = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    for old in snapshots[: max(0, len(snapshots) - settings.RAW_KEEP_SNAPSHOTS)]:
        shutil.rmtree(os.path.join(base, old), ignore_errors=True)
        logger.info(f"raw 스냅샷 정리: {endpoint}/{old}")


def latest_snapshot(endpoint: str) -> str | None:
    base = os.path.join(raw_root(), endpoint)
    if not os.path.isdir(base):
        return None
    snapshots = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    return snapshots[-1] if snapshots else None


def load_page(endpoint: str, snapshot: str, page: int) -> dict | None:
    path = _page_path(endpoint, snapshot, page)
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)
