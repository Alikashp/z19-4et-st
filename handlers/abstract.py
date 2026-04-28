from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from states import AbstractStates
from keyboards import (
    input_type_kb, level_kb, volume_kb,
    confirm_generation_kb, after_report_kb,
)
from prompts import abstract_prompt, LEVEL_LABELS, VOLUME_LABELS
from services.llm import generate_text
from services.file_generator import generate_pdf, get_preview
from services.document_reader import read_document
from handlers.common import check_balance, deduct_generation

router = Router()
MATERIAL = "abstract"


@router.callback_query(lambda c: c.data == "menu:abstract")
async def abstract_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AbstractStates.choosing_input_type)
    await callback.message.answer(
        "📚 <b>Реферат</b>\n\nВыбери вариант создания:",
        parse_mode="HTML",
        reply_markup=input_type_kb(MATERIAL),
    )
    await callback.answer()


@router.callback_query(AbstractStates.choosing_input_type, lambda c: c.data.startswith("abstract:input:"))
async def abstract_input_type(callback: CallbackQuery, state: FSMContext):
    input_type = callback.data.split(":")[-1]
    await state.update_data(input_type=input_type)

    if input_type == "topic":
        await state.set_state(AbstractStates.waiting_for_topic)
        await callback.message.answer("✍️ Введи тему реферата:")
    elif input_type == "text":
        await state.set_state(AbstractStates.waiting_for_text)
        await callback.message.answer("📄 Отправь текст, на основе которого нужно подготовить реферат:")
    await callback.answer()


@router.message(AbstractStates.waiting_for_topic)
async def abstract_got_topic(message: Message, state: FSMContext):
    await state.update_data(topic=message.text, material_text=message.text)
    await state.set_state(AbstractStates.choosing_level)
    await message.answer("🎓 Выбери уровень подготовки:", reply_markup=level_kb(MATERIAL))


@router.message(AbstractStates.waiting_for_text)
async def abstract_got_text(message: Message, state: FSMContext):
    await state.update_data(topic="(из текста)", material_text=message.text)
    await state.set_state(AbstractStates.choosing_level)
    await message.answer("🎓 Выбери уровень подготовки:", reply_markup=level_kb(MATERIAL))


@router.callback_query(AbstractStates.choosing_level, lambda c: c.data.startswith("abstract:level:"))
async def abstract_level(callback: CallbackQuery, state: FSMContext):
    level = callback.data.split(":")[-1]
    await state.update_data(level=level)
    await state.set_state(AbstractStates.choosing_volume)
    await callback.message.answer("📏 Выбери объём:", reply_markup=volume_kb(MATERIAL))
    await callback.answer()


@router.callback_query(AbstractStates.choosing_volume, lambda c: c.data.startswith("abstract:volume:"))
async def abstract_volume(callback: CallbackQuery, state: FSMContext):
    volume = callback.data.split(":")[-1]
    await state.update_data(volume=volume)
    data = await state.get_data()

    level_label = LEVEL_LABELS.get(data["level"], data["level"])
    volume_label = VOLUME_LABELS.get(volume, volume)

    text = (
        f"📋 <b>Проверь параметры:</b>\n\n"
        f"📌 Тема: <b>{data.get('topic', '—')}</b>\n"
        f"🎓 Уровень: <b>{level_label}</b>\n"
        f"📏 Объём: <b>{volume_label}</b>"
    )
    await state.set_state(AbstractStates.confirming)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=confirm_generation_kb(MATERIAL))
    await callback.answer()


@router.callback_query(AbstractStates.confirming, lambda c: c.data == "abstract:generate:edit")
async def abstract_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AbstractStates.choosing_input_type)
    await callback.message.answer("Выбери вариант создания:", reply_markup=input_type_kb(MATERIAL))
    await callback.answer()


@router.callback_query(AbstractStates.confirming, lambda c: c.data == "abstract:generate:confirm")
async def abstract_generate(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return

    data = await state.get_data()
    await state.set_state(AbstractStates.generating)
    msg = await callback.message.answer("⏳ Генерирую реферат, подожди немного...")

    try:
        prompt = abstract_prompt(
            topic=data.get("material_text") or data.get("topic", ""),
            level=data.get("level", "school"),
            volume=data.get("volume", "auto"),
        )
        full_text = await generate_text(prompt, max_tokens=5000)
        await state.update_data(generated_text=full_text)

        safe_topic = (data.get("topic") or "referat")[:30].replace(" ", "_").replace("/", "_")
        pdf_filename = f"abstract_{callback.from_user.id}_{safe_topic}.pdf"
        pdf_path = generate_pdf(full_text, pdf_filename)

        preview = get_preview(full_text, lines=3)
        await deduct_generation(db, callback.from_user.id)

        await msg.delete()
        await callback.message.answer(
            f"✅ <b>Реферат готов!</b>\n\n{preview}\n\n<i>...полный текст в файле ниже 👇</i>",
            parse_mode="HTML",
        )
        await callback.message.answer_document(
            FSInputFile(pdf_path),
            caption="📄 Полный реферат",
            reply_markup=after_report_kb("реферат", MATERIAL),
        )

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка при генерации: {e}\n\nПопробуй ещё раз.")

    await callback.answer()


# Follow-up handlers (speech/qa — дублируем логику из report.py через общий модуль)
@router.callback_query(lambda c: c.data == f"followup:{MATERIAL}:speech")
async def abstract_followup_speech(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return
    data = await state.get_data()
    material_text = data.get("generated_text", "")
    if not material_text:
        await callback.message.answer("❌ Не найден материал. Начни заново.")
        await callback.answer()
        return
    from handlers.report import _generate_speech
    await _generate_speech(callback, db, material_text)
    await callback.answer()


@router.callback_query(lambda c: c.data == f"followup:{MATERIAL}:qa")
async def abstract_followup_qa(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return
    data = await state.get_data()
    material_text = data.get("generated_text", "")
    if not material_text:
        await callback.message.answer("❌ Не найден материал. Начни заново.")
        await callback.answer()
        return
    from handlers.report import _generate_qa
    await _generate_qa(callback, db, material_text)
    await callback.answer()
