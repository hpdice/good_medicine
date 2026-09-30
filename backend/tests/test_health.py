"""헬스체크는 DB까지 확인해야 한다 — 외부 감시가 실제 장애를 알 수 있도록."""
from httpx import ASGITransport, AsyncClient

from app.db.session import get_db
from app.main import app


async def test_health_ok_when_db_reachable(client):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok"}


async def test_health_503_when_db_down(client):
    class _BrokenSession:
        async def execute(self, *args, **kwargs):
            raise ConnectionError("db down")

    async def _broken_db():
        yield _BrokenSession()

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _broken_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.get("/health")
    finally:
        app.dependency_overrides[get_db] = previous
    assert res.status_code == 503
    assert res.json()["db"] == "down"
