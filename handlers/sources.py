from aiogram import Router
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from states import SourcesStates
from keyboards import (
    sources_variant_kb, sources_format_kb,
    sources_count_kb, after_sources_kb, main_menu_kb,
)
from prompts import (
    sources_format_prompt, FORMAT_DIFF_TEXT
)
from services.llm import generate_text
from services.sources_pipeline import generate_sources_by_topic
from handlers.common import check_balance, deduct_generation

router = Router()

def _resolve_requested_count(raw_count: str) -> int:
    """Преобразует count из кнопок (например, `5-7`) или ручного ввода в int."""
    value = (raw_count or "").strip()
    if "-" in value:
        parts = [part.strip() for part in value.split("-", 1)]
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            return int(parts[1])
    if value.isdigit():
        return int(value)
    raise ValueError(f"Некорректное значение count: {raw_count}")


@router.callback_query(lambda c: c.data == "menu:sources")
async def sources_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SourcesStates.choosing_variant)
    await callback.message.answer(
        "🔗 <b>Оформление источников</b>\n\nВыбери вариант:",
        parse_mode="HTML",
        reply_markup=sources_variant_kb(),
    )
    await callback.answer()


# ─── Variant: by topic ───────────────────────────────────────

@router.callback_query(SourcesStates.choosing_variant, lambda c: c.data == "sources:variant:topic")
async def sources_by_topic_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SourcesStates.waiting_for_topic)
    await callback.message.answer("✍️ Введи тему, по которой нужно подобрать источники:")
    await callback.answer()


@router.message(SourcesStates.waiting_for_topic)
async def sources_got_topic(message: Message, state: FSMContext):
    await state.update_data(topic=message.text, variant="topic")
    await state.set_state(SourcesStates.choosing_format)
    await message.answer(
        "📋 В каком формате оформить источники?",
        reply_markup=sources_format_kb("sources_topic"),
    )


@router.callback_query(
    SourcesStates.choosing_format,
    lambda c: c.data.startswith("sources_topic:format:"),
)
async def sources_topic_format(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[-1]

    if choice == "diff":
        await callback.message.answer(FORMAT_DIFF_TEXT, parse_mode="HTML")
        await callback.answer()
        return

    await state.update_data(source_format=choice)
    await state.set_state(SourcesStates.choosing_count)
    await callback.message.answer(
        "🔢 Выбери количество источников или введи цифру от 1 до 15:",
        reply_markup=sources_count_kb(),
    )
    await callback.answer()


@router.callback_query(
    SourcesStates.choosing_count,
    lambda c: c.data.startswith("sources:count:"),
)
async def sources_count_selected(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    count = callback.data.split(":")[-1]
    await state.update_data(count=count)
    await _generate_sources_by_topic(callback, state, db)
    await callback.answer()


@router.message(SourcesStates.choosing_count)
async def sources_count_custom(message: Message, state: FSMContext, db: AsyncSession):
    try:
        count = int(message.text.strip())
        if not (1 <= count <= 15):
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введи цифру от 1 до 15.")
        return
    await state.update_data(count=str(count))
    # Эмулируем callback через message
    data = await state.get_data()
    msg = await message.answer("⏳ Подбираю источники...")
    try:
        if not await check_balance(db, message.from_user.id, message=message):
            await msg.delete()
            return
        result = await generate_sources_by_topic(
            topic=data.get("topic", ""),
            count=_resolve_requested_count(data.get("count", "5")),
            fmt=data.get("source_format", "ГОСТ"),
        )
        await deduct_generation(db, message.from_user.id)
        await msg.delete()
        await message.answer(
            f"🔗 <b>Источники по теме:</b>\n\n{result}",
            parse_mode="HTML",
            reply_markup=after_sources_kb(),
        )
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


async def _generate_sources_by_topic(
    callback: CallbackQuery, state: FSMContext, db: AsyncSession
):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        return
    data = await state.get_data()
    msg = await callback.message.answer("⏳ Подбираю источники...")
    try:
        result = await generate_sources_by_topic(
            topic=data.get("topic", ""),
            count=_resolve_requested_count(data.get("count", "5")),
            fmt=data.get("source_format", "ГОСТ"),
        )
        await deduct_generation(db, callback.from_user.id)
        await msg.delete()
        await callback.message.answer(
            f"🔗 <b>Источники по теме «{data.get('topic', '')}»:</b>\n\n{result}",
            parse_mode="HTML",
            reply_markup=after_sources_kb(),
        )
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


# ─── Variant: own sources ─────────────────────────────────────

@router.callback_query(SourcesStates.choosing_variant, lambda c: c.data == "sources:variant:own")
async def sources_own_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SourcesStates.waiting_for_sources)
    await callback.message.answer(
        "✏️ Напиши свои источники текстом — я оформлю их в нужном формате.\n\n"
        "<i>Можно писать в любом виде, по одному или несколько в сообщении.</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SourcesStates.waiting_for_sources)
async def sources_got_own(message: Message, state: FSMContext):
    await state.update_data(sources_text=message.text, variant="own")
    await state.set_state(SourcesStates.choosing_own_format)
    await message.answer(
        "📋 В каком формате оформить?",
        reply_markup=sources_format_kb("sources_own"),
    )


@router.callback_query(
    SourcesStates.choosing_own_format,
    lambda c: c.data.startswith("sources_own:format:"),
)
async def sources_own_format(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    choice = callback.data.split(":")[-1]

    if choice == "diff":
        await callback.message.answer(FORMAT_DIFF_TEXT, parse_mode="HTML")
        await callback.answer()
        return

    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return

    data = await state.get_data()
    msg = await callback.message.answer("⏳ Оформляю источники...")

    try:
        prompt = sources_format_prompt(
            sources=data.get("sources_text", ""),
            fmt=choice,
        )
        result = await generate_text(prompt, max_tokens=2000)
        await deduct_generation(db, callback.from_user.id)
        await msg.delete()
        await callback.message.answer(
            f"🔗 <b>Оформленные источники ({choice}):</b>\n\n{result}",
            parse_mode="HTML",
            reply_markup=after_sources_kb(),
        )
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")

    await callback.answer()


# ─── Cross-flow: sources from after_report ────────────────────

@router.callback_query(lambda c: c.data == "followup:speech:qa")
async def speech_followup_qa(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    """После речи → вопросы и ответы."""
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return
    data = await state.get_data()
    material_text = data.get("generated_text") or data.get("speech_text", "")
    if not material_text:
        await callback.message.answer("❌ Не найден материал. Начни заново.")
        await callback.answer()
        return
    from handlers.report import _generate_qa
    await _generate_qa(callback, db, material_text)
    await callback.answer()


@router.callback_query(lambda c: c.data == "followup:qa:speech")
async def qa_followup_speech(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    """После Q&A → речь."""
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return
    data = await state.get_data()
    material_text = data.get("generated_text") or ""
    if not material_text:
        await callback.message.answer("❌ Не найден материал. Начни заново.")
        await callback.answer()
        return
    from handlers.report import _generate_speech
    await _generate_speech(callback, db, material_text)
    await callback.answer()
