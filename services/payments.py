import aiohttp
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Payment, User
from config import (
    YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY,
    PAYMENT_PROVIDER, TARIFFS
)


async def create_payment(
    db: AsyncSession,
    user_id: int,
    tariff_index: int,
    return_url: str = "https://t.me/",
) -> dict:
    """
    Создаёт платёж через YooKassa (или заглушку).
    Возвращает словарь с payment_url и payment_id.
    """
    if tariff_index < 0 or tariff_index >= len(TARIFFS):
        raise ValueError("Неверный индекс тарифа")

    tariff = TARIFFS[tariff_index]

    # Сохраняем платёж в БД со статусом pending
    payment = Payment(
        user_id=user_id,
        provider=PAYMENT_PROVIDER,
        tariff_name=tariff["name"],
        amount=tariff["price"],
        generations_count=tariff["generations"],
        status="pending",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
        # Заглушка: сразу начисляем генерации
        await _apply_payment_stub(db, payment, user_id, tariff)
        return {
            "payment_url": None,
            "payment_id": f"stub_{payment.id}",
            "stub": True,
        }

    # Реальный вызов YooKassa API
    idempotency_key = str(uuid.uuid4())
    payload = {
        "amount": {"value": f"{tariff['price']:.2f}", "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": return_url},
        "capture": True,
        "description": f"Тариф «{tariff['name']}» — {tariff['generations']} генераций",
        "metadata": {
            "payment_db_id": payment.id,
            "user_id": user_id,
            "tariff_name": tariff["name"],
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.yookassa.ru/v3/payments",
            auth=aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY),
            headers={"Idempotence-Key": idempotency_key, "Content-Type": "application/json"},
            json=payload,
        ) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                raise RuntimeError(f"YooKassa error {resp.status}: {text}")
            data = await resp.json()

    payment_url = data["confirmation"]["confirmation_url"]
    payment_id = data["id"]

    payment.payment_id = payment_id
    payment.payment_url = payment_url
    await db.commit()

    return {"payment_url": payment_url, "payment_id": payment_id, "stub": False}


async def confirm_payment(db: AsyncSession, payment_id: str, user_id: int):
    """
    Вызывается при подтверждении оплаты (через webhook или polling).
    Начисляет генерации пользователю.
    """
    result = await db.execute(
        select(Payment).where(Payment.payment_id == payment_id)
    )
    payment = result.scalar_one_or_none()
    if not payment or payment.status == "paid":
        return

    payment.status = "paid"
    payment.paid_at = datetime.utcnow()
    await db.commit()

    # Начисляем генерации
    result = await db.execute(select(User).where(User.telegram_id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.balance_generations += payment.generations_count
        await db.commit()


async def _apply_payment_stub(db, payment, user_id, tariff):
    """Начисляет генерации сразу (режим заглушки без реального платёжного шлюза)."""
    payment.status = "paid"
    payment.paid_at = datetime.utcnow()
    payment.payment_id = f"stub_{payment.id}"
    await db.commit()

    result = await db.execute(select(User).where(User.telegram_id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.balance_generations += tariff["generations"]
        await db.commit()
