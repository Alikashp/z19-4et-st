from aiogram import Router
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards import tariffs_kb, back_to_main_kb
from services.payments import create_payment
from config import TARIFFS

router = Router()


@router.callback_query(lambda c: c.data == "menu:tariffs")
async def show_tariffs(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lines = ["💳 <b>Выбери тариф:</b>\n"]
    for t in TARIFFS:
        lines.append(
            f"<b>{t['name']}</b> — {t['label']}\n"
            f"<i>{t['description']}</i>\n"
        )
    await callback.message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=tariffs_kb(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("pay:tariff:"))
async def process_tariff_payment(callback: CallbackQuery, db: AsyncSession):
    tariff_index = int(callback.data.split(":")[-1])
    tariff = TARIFFS[tariff_index]

    msg = await callback.message.answer("⏳ Создаю платёж...")

    try:
        result = await create_payment(
            db=db,
            user_id=callback.from_user.id,
            tariff_index=tariff_index,
            return_url=f"https://t.me/{(await callback.bot.get_me()).username}",
        )

        if result.get("stub"):
            # Режим заглушки — генерации начислены сразу
            await msg.delete()
            await callback.message.answer(
                f"✅ <b>Тариф «{tariff['name']}» активирован!</b>\n\n"
                f"🎁 Начислено <b>{tariff['generations']} генераций</b>.\n\n"
                f"<i>⚠️ Режим разработки: реальный платёж не выполнялся.</i>",
                parse_mode="HTML",
                reply_markup=back_to_main_kb(),
            )
        else:
            await msg.delete()
            await callback.message.answer(
                f"💳 <b>Оплата тарифа «{tariff['name']}»</b>\n\n"
                f"Сумма: <b>{tariff['price']} ₽</b>\n"
                f"Генераций: <b>{tariff['generations']}</b>\n\n"
                f"👉 <a href=\"{result['payment_url']}\">Перейти к оплате</a>\n\n"
                f"<i>После оплаты генерации будут начислены автоматически.</i>",
                parse_mode="HTML",
                reply_markup=back_to_main_kb(),
            )
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка при создании платежа: {e}")

    await callback.answer()


@router.callback_query(lambda c: c.data == "menu:settings")
async def show_settings(callback: CallbackQuery, db: AsyncSession):
    from sqlalchemy import select
    from models import User
    result = await db.execute(select(User).where(User.telegram_id == callback.from_user.id))
    user = result.scalar_one_or_none()

    balance = user.balance_generations if user else 0
    await callback.message.answer(
        f"⚙️ <b>Настройки</b>\n\n"
        f"👤 Имя: {callback.from_user.first_name or '—'}\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"🎟 Баланс генераций: <b>{balance}</b>\n\n"
        f"Для пополнения баланса — выбери тариф.",
        parse_mode="HTML",
        reply_markup=tariffs_kb(),
    )
    await callback.answer()
