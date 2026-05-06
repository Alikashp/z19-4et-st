from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from models import Base
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def run_migrations():
    """Безопасно добавляет новые колонки к существующим таблицам. Данные не трогает."""
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN free_generations_reset_at TIMESTAMP"
            ))
        except Exception:
            pass  # колонка уже есть — всё ок


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
