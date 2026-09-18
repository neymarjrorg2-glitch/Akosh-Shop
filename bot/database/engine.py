from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import DATABASE_URL
from bot.database.models import Base

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Barcha jadvallarni (agar mavjud bo'lmasa) yaratadi."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
