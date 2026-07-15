"""E2E 테스트 공통 픽스처.

실제 운영 DB(drugtest_db, 35,299개 약품·324,321개 상호작용)는 절대 건드리지 않는다.
같은 Postgres 인스턴스 안에 별도의 `drugtest_test_db`를 만들어 스키마만 복제한다.

엔진을 세션 스코프로 공유하면 asyncpg 커넥션이 pytest-asyncio의 테스트별 이벤트
루프와 어긋나 "another operation is in progress" 오류가 난다 — 그래서 엔진 자체를
테스트 함수 스코프로 만들어, 매 테스트가 자기 이벤트 루프 안에서 엔진을 새로
만들고 정리한다 (테이블 수가 적어 비용은 미미하다).
"""
import os

os.environ.setdefault("DEBUG", "false")
# 로그인 엔드포인트는 5회/15분으로 강하게 제한되어 있어, 여러 테스트가
# 순차적으로 로그인을 호출하면 실제 슬로우API 제한에 걸린다. 테스트에서는 완화한다.
os.environ["LOGIN_RATE_LIMIT"] = "1000/minute"

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
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


@pytest_asyncio.fixture
async def test_engine():
    await _ensure_test_database()
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
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
