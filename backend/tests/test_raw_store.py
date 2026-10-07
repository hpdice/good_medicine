"""원본 응답 보관(bronze) 테스트 — 저장·재생·스냅샷 정리·저장 실패 무영향.

공공 API 는 부르지 않는다. `_fetch_page` 안의 보관/재생 경로만 검증한다.
"""
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.services.public_data_service import PublicDataService, raw_store

URL = "http://example.test/svc/getSomething"
PAGE = {"body": {"items": [{"ITEM_SEQ": "1", "한글": "값"}], "totalCount": 1}}


@pytest.fixture(autouse=True)
def _raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "RAW_RESPONSE_SAVE", True)
    monkeypatch.setattr(settings, "RAW_KEEP_SNAPSHOTS", 2)


def _client(payload: dict) -> httpx.AsyncClient:
    handler = lambda request: httpx.Response(200, json=payload)  # noqa: E731
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_saves_raw_and_replay_reads_it_without_http():
    svc = PublicDataService(None)  # type: ignore[arg-type]
    async with _client(PAGE) as client:
        got = await svc._fetch_page(client, URL, {"pageNo": 3})
    assert got == PAGE

    replay = PublicDataService(None)  # type: ignore[arg-type]
    replay.replay_snapshot = "latest"

    class Boom:  # replay 모드면 HTTP 클라이언트를 쓰면 안 된다
        async def get(self, *a, **k):
            raise AssertionError("replay 중 API 호출")

    assert await replay._fetch_page(Boom(), URL, {"pageNo": 3}) == PAGE   # 한글 보존
    assert await replay._fetch_page(Boom(), URL, {"pageNo": 4}) is None   # 없는 페이지 → None(상위가 중단)


async def test_service_key_is_not_stored():
    svc = PublicDataService(None)  # type: ignore[arg-type]
    async with _client(PAGE) as client:
        await svc._fetch_page(client, URL, {"pageNo": 1, "serviceKey": "SECRET-KEY"})
    import gzip
    import pathlib
    files = list(pathlib.Path(settings.SYNC_STATE_DIR, "raw").rglob("*.json.gz"))
    assert files and all(b"SECRET-KEY" not in gzip.open(f).read() for f in files)


async def test_save_failure_does_not_break_sync(monkeypatch):
    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(raw_store, "save_page", broken)
    svc = PublicDataService(None)  # type: ignore[arg-type]
    async with _client(PAGE) as client:
        assert await svc._fetch_page(client, URL, {"pageNo": 1}) == PAGE


def test_old_snapshots_are_pruned():
    for day in ("20260101", "20260201", "20260301"):
        raw_store.save_page("ep", day, 1, PAGE)
    assert sorted(p.name for p in Path(raw_store.raw_root(), "ep").iterdir()) == ["20260201", "20260301"]
    assert raw_store.latest_snapshot("ep") == "20260301"
