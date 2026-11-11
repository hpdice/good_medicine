"""E2E 테스트 공통 픽스처.

실제 운영 DB(drugtest_db)는 절대 건드리지 않는다 — 같은 Postgres 인스턴스 안에
별도의 `drugtest_test_db`를 만들어 스키마만 복제한다.

- 스키마 생성(확장 + create_all)은 **세션당 1회**(`_prepare_schema`).
- 테스트 격리는 매 테스트 시작 시 전체 테이블 `TRUNCATE`(`test_engine`)로 한다.
- 엔진 객체는 함수 스코프로 새로 만든다 — 엔진을 세션 스코프로 공유하면 asyncpg
  커넥션이 pytest-asyncio의 테스트별 이벤트 루프와 어긋나 "another operation is
  in progress" 오류가 나기 때문. (엔진 생성 자체는 저렴, DDL 이 비쌌던 것)
"""
import os

os.environ.setdefault("DEBUG", "false")
# 로그인 엔드포인트의 IP 단위 제한(운영 20회/15분)에 여러 테스트가 순차적으로 로그인을 호출하다
# 걸리지 않도록 테스트에서는 완화한다. (계정별 실패 제한은 아래 autouse 픽스처가 테스트마다 초기화한다.)
os.environ["LOGIN_RATE_LIMIT"] = "1000/minute"
# 테스트는 거의 매번 회원가입+로그인(=bcrypt 해시+검증)을 한다. 운영 코스트(12)면
# 테스트 1개당 수백 ms 씩 붙으므로 4 로 낮춘다 (보안 무관, 속도만).
os.environ["BCRYPT_ROUNDS"] = "4"

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.login_guard import login_guard
from app.db.base import Base
from app.db.session import get_db
from app.main import app

TEST_DB_NAME = "drugtest_test_db"
TEST_DATABASE_URL = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


async def _ensure_test_database() -> None:
    admin_engine = create_async_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    await admin_engine.dispose()


def _drugs_master_view_sql() -> str:
    """`drugs_master` 뷰 정의 — 마이그레이션 0021이 가진 문자열을 그대로 쓴다(정의가 한 곳에만 있도록)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0021_drugs_master_view.py"
    spec = importlib.util.spec_from_file_location("migration_0021_drugs_master_view", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.DRUGS_MASTER_VIEW_SQL


@pytest.fixture(scope="session", autouse=True)
def _prepare_schema():
    """세션당 1회: 테스트 DB 생성 + 확장 + 스키마(create_all).

    자체 이벤트 루프(`asyncio.run`)에서 완결·정리하므로 pytest-asyncio 의
    테스트별 루프와 겹치지 않는다.
    """

    async def _setup() -> None:
        await _ensure_test_database()
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
        async with engine.begin() as conn:
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            # 원천 테이블을 지우려면 뷰부터. 예전 테스트 DB에는 같은 이름의 테이블이 남아 있을 수 있어 종류를 보고 지운다.
            await conn.execute(text(
                "DO $$ DECLARE k char; BEGIN "
                "SELECT relkind INTO k FROM pg_class WHERE relname = 'drugs_master' AND relnamespace = 'public'::regnamespace; "
                "IF k = 'v' THEN DROP VIEW drugs_master; ELSIF k = 'r' THEN DROP TABLE drugs_master; END IF; END $$"
            ))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text(_drugs_master_view_sql()))  # 뷰는 create_all 대상이 아니다 — 마이그레이션과 같은 정의
        await engine.dispose()

    asyncio.run(_setup())
    yield


@pytest.fixture(autouse=True)
def _no_permit_detail_network(monkeypatch):
    """복약함 추가·약 상세 조회가 허가정보 상세 API(공공데이터)를 실제로 부르지 않게 막는다.
    상세 보강을 검증하는 테스트는 이 패치를 자기 가짜 `_fetch`로 다시 덮어쓴다."""
    from app.services.drug_detail_service import DrugDetailService

    async def _offline(self, item_seq):
        return None

    monkeypatch.setattr(DrugDetailService, "_fetch", _offline)


@pytest_asyncio.fixture(autouse=True)
async def _drain_detail_background_tasks():
    """약을 담을 때 못 받은 상세를 뒤에서 마저 받는 작업(`schedule_detail_completion`)이 테스트가 끝난 뒤까지
    남지 않게, 매 테스트가 끝나면 기다렸다가 정리한다."""
    yield
    from app.services import drug_detail_service

    pending = list(drug_detail_service._background)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_login_guard():
    """계정별 로그인 실패 카운터는 프로세스 메모리에 있어 테스트 사이에 새어 나간다 — 매번 비운다."""
    login_guard.clear()
    yield
    login_guard.clear()


_TRUNCATE_ALL = "TRUNCATE {} RESTART IDENTITY CASCADE".format(
    ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
)


@pytest_asyncio.fixture
async def test_engine(_prepare_schema):
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.execute(text(_TRUNCATE_ALL))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(test_engine):
    """테스트 안에서 시드 데이터를 직접 넣을 때 쓰는 세션 팩토리."""
    return async_sessionmaker(bind=test_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def client(test_engine, session_factory):
    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as ac:
        yield ac

    app.dependency_overrides.clear()
