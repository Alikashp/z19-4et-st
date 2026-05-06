from datetime import datetime
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import User
from keyboards import no_balance_kb

FREE_GENERATIONS_PER_MONTH = 10
FREE_GENERATION_INTERVAL_DAYS = 30


async def get_or_create_user(
    db: AsyncSession,
    message: Message,
    referral_source: str | None = None,
) -> User:
    result = await db.execute(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    user = result.scalar_one_or_none()
    if not user:
        now = datetime.utcnow()
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username or None,
            first_name=message.from_user.first_name or None,
            balance_generations=FREE_GENERATIONS_PER_MONTH,
            free_generations_reset_at=now,
            referral_source=referral_source,  # None если пришёл напрямую
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def check_and_refresh_free_generations(db: AsyncSession, user: User) -> bool:
    now = datetime.utcnow()
    reset_at = user.free_generations_reset_at

    if reset_at is None or (now - reset_at).days >= FREE_GENERATION_INTERVAL_DAYS:
        user.balance_generations += FREE_GENERATIONS_PER_MONTH
        user.free_generations_reset_at = now
        await db.commit()
        return True
    return False


async def get_user_by_telegram_id(db: AsyncSession, telegram_id: int) -> User | None:
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def check_balance(
    db: AsyncSession,
    telegram_id: int,
    callback: CallbackQuery | None = None,
    message: Message | None = None,
) -> bool:
    user = await get_user_by_telegram_id(db, telegram_id)
    if not user or user.balance_generations <= 0:
        text = (
            "😔 У тебя закончились генерации.\n\n"
            "Пополни баланс, чтобы продолжить создавать учебные материалы."
        )
        if callback:
            await callback.message.answer(text, reply_markup=no_balance_kb())
        elif message:
            await message.answer(text, reply_markup=no_balance_kb())
        return False
    return True


async def deduct_generation(db: AsyncSession, telegram_id: int):
    user = await get_user_by_telegram_id(db, telegram_id)
    if user and user.balance_generations > 0:
        user.balance_generations -= 1
        await db.commit()
