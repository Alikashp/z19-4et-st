import logging
from datetime import datetime, timedelta
from sqlalchemy import select, or_
from models import User
from database import AsyncSessionLocal

logger = logging.getLogger(__name__)

FREE_GENERATIONS_PER_MONTH = 10
FREE_GENERATION_INTERVAL_DAYS = 30


async def refresh_free_generations_for_all_users():
    """
    Запускается раз в сутки. Начисляет 10 бесплатных генераций всем пользователям,
    у кого прошло 30 дней с последнего начисления.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(days=FREE_GENERATION_INTERVAL_DAYS)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(
                or_(
                    User.free_generations_reset_at == None,
                    User.free_generations_reset_at <= cutoff,
                )
            )
        )
        users = result.scalars().all()

        for user in users:
            user.balance_generations += FREE_GENERATIONS_PER_MONTH
            user.free_generations_reset_at = now

        await session.commit()

    if users:
        logger.info(f"Начислены бесплатные генерации {len(users)} пользователям")
