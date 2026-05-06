from datetime import datetime
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import User
from keyboards import no_balance_kb

FREE_GENERATIONS_PER_MONTH = 10
FREE_GENERATION_INTERVAL_DAYS = 30


async def get_or_create_user(db: AsyncSession, message: Message) -> User:
    """Возвращает пользователя из БД или создаёт нового с 10 бесплатными генерациями."""
    result = await db.execute(
        select(User).where(User.telegram_id == message.from_user.id)
    )
    user = result.scalar_one_or_none()
    if not user:
        now = datetime.utcnow()
        # username может быть None — это нормально, поле nullable
        username = message.from_user.username or None
        first_name = message.from_user.first_name or None
        user = User(
            telegram_id=message.from_user.id,
            username=username,
            first_name=first_name,
            balance_generations=FREE_GENERATIONS_PER_MONTH,
            free_generations_reset_at=now,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def check_and_refresh_free_generations(db: AsyncSession, user: User) -> bool:
    """
    Проверяет, прошло ли 30 дней с последнего начисления бесплатных генераций.
    Если да — начисляет ещё 10 и обновляет дату. Возвращает True, если генерации были добавлены.
    """
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
    """
    Проверяет баланс пользователя.
    Если баланс 0 — отправляет сообщение с предложением купить тариф и возвращает False.
    """
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
    """Списывает одну генерацию с баланса пользователя."""
    user = await get_user_by_telegram_id(db, telegram_id)
    if user and user.balance_generations > 0:
        user.balance_generations -= 1
        await db.commit()
