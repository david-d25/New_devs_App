import logging
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from ..config import settings

logger = logging.getLogger(__name__)


def _async_url(url: str) -> str:
    for prefix in ("postgresql+asyncpg://",):
        if url.startswith(prefix):
            return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


class DatabasePool:
    def __init__(self):
        self.engine = None
        self.session_factory = None

    async def initialize(self):
        if self.session_factory:
            return
        self.engine = create_async_engine(
            _async_url(settings.database_url),
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout,
            pool_pre_ping=True,
            pool_recycle=settings.database_pool_recycle,
            echo=False,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info("✅ Database connection pool initialized")

    async def close(self):
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None

    @asynccontextmanager
    async def get_session(self):
        if not self.session_factory:
            raise RuntimeError("Database pool not initialized")
        async with self.session_factory() as session:
            yield session


db_pool = DatabasePool()


async def get_db_session():
    async with db_pool.get_session() as session:
        yield session