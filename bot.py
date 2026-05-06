import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TG_BOT_API_KEY
from database import init_db, run_migrations, AsyncSessionLocal
from handlers import start, report, abstract, presentation, sources, tariffs
from services.scheduler import refresh_free_generations_for_all_users
from aiogram.types import BotCommand

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def db_middleware(handler, event, data):
    async with AsyncSessionLocal() as session:
        data["db"] = session
        return await handler(event, data)


async def main():
    if not TG_BOT_API_KEY:
        raise RuntimeError("TG_BOT_API_KEY не задан в .env")

    await init_db()
    await run_migrations()
    logger.info("Database initialized and migrations applied")

    # Планировщик: проверяет всех юзеров раз в сутки
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        refresh_free_generations_for_all_users,
        trigger="interval",
        hours=24,
        id="free_generations_refresh",
    )
    scheduler.start()
    logger.info("Scheduler started")

    bot = Bot(token=TG_BOT_API_KEY)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)

    dp.include_router(start.router)
    dp.include_router(report.router)
    dp.include_router(abstract.router)
    dp.include_router(presentation.router)
    dp.include_router(sources.router)
    dp.include_router(tariffs.router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="report", description="Сделать доклад"),
        BotCommand(command="abstract", description="Сделать реферат"),
        BotCommand(command="presentation", description="Сделать презентацию"),
        BotCommand(command="sources", description="Оформить источники"),
        BotCommand(command="tariffs", description="Тарифы"),
        BotCommand(command="settings", description="Настройки"),
    ])

    logger.info("Bot starting...")

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
