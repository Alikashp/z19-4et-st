import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncSession

from config import TG_BOT_API_KEY
from database import init_db, AsyncSessionLocal
from handlers import start, report, abstract, presentation, sources, tariffs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def db_middleware(handler, event, data):
    """Middleware: добавляет сессию БД в каждый хэндлер."""
    async with AsyncSessionLocal() as session:
        data["db"] = session
        return await handler(event, data)


async def main():
    if not TG_BOT_API_KEY:
        raise RuntimeError("TG_BOT_API_KEY не задан в .env")

    await init_db()
    logger.info("Database initialized")

    bot = Bot(token=TG_BOT_API_KEY)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Подключаем middleware для БД
    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)

    # Регистрируем роутеры
    dp.include_router(start.router)
    dp.include_router(report.router)
    dp.include_router(abstract.router)
    dp.include_router(presentation.router)
    dp.include_router(sources.router)
    dp.include_router(tariffs.router)

    logger.info("Bot starting...")

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
