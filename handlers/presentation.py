from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from states import PresentationStates
from keyboards import (
    presentation_settings_kb,
    presentation_language_kb, presentation_slides_kb,
    presentation_design_kb, after_presentation_kb,
    fibonacci_redirect_kb,
)
from services.fibonacci_api import create_presentation
from handlers.common import check_balance, deduct_generation

router = Router()

DEFAULT_SETTINGS = {
    "language": "Русский",
    "slides_count": 8,
    "design": "Креативный",
}


def _settings_text(data: dict) -> str:
    topic = data.get("topic", "не указана")
    return (
        f"⚙️ <b>Ваши настройки для презентации:</b>\n\n"
        f"🎭 Тема: <b>{topic}</b>\n"
        f"🌐 Язык презентации: <b>{data.get('language', DEFAULT_SETTINGS['language'])}</b>\n"
        f"🗂 Количество слайдов: <b>{data.get('slides_count', DEFAULT_SETTINGS['slides_count'])}</b>\n"
        f"🎨 Дизайн: <b>{data.get('design', DEFAULT_SETTINGS['design'])}</b>"
    )


@router.callback_query(lambda c: c.data == "menu:presentation")
async def presentation_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "Создавай лучшие презентации в боте Fibonacci AI @Fibonacci_presentation_bot",
        parse_mode="HTML",
        reply_markup=fibonacci_redirect_kb(),
    )
    await callback.answer()


@router.callback_query(
    PresentationStates.choosing_input_type,
    lambda c: c.data.startswith("presentation:input:"),
)
async def presentation_input_type(callback: CallbackQuery, state: FSMContext):
    input_type = callback.data.split(":")[-1]
    await state.update_data(input_type=input_type, **DEFAULT_SETTINGS)

    if input_type == "topic":
        await state.set_state(PresentationStates.waiting_for_topic)
        await callback.message.answer("✍️ Введи тему презентации:")
    elif input_type == "text":
        await state.set_state(PresentationStates.waiting_for_text)
        await callback.message.answer(
            "📄 Отправь текст сообщением или документ с расширением <b>.txt</b> или <b>.docx</b> "
            "и размером не более 110 КБ.",
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(PresentationStates.waiting_for_topic)
async def presentation_got_topic(message: Message, state: FSMContext):
    await state.update_data(topic=message.text)
    await state.set_state(PresentationStates.settings)
    data = await state.get_data()
    await message.answer(
        _settings_text(data),
        parse_mode="HTML",
        reply_markup=presentation_settings_kb(),
    )


@router.message(PresentationStates.waiting_for_text, F.text)
async def presentation_got_text(message: Message, state: FSMContext):
    # Используем первые 200 символов как тему
    topic = message.text[:200] if message.text else "По тексту"
    await state.update_data(topic=topic, raw_text=message.text)
    await state.set_state(PresentationStates.settings)
    data = await state.get_data()
    await message.answer(
        _settings_text(data),
        parse_mode="HTML",
        reply_markup=presentation_settings_kb(),
    )


@router.message(PresentationStates.waiting_for_text, F.document)
async def presentation_got_document(message: Message, state: FSMContext, bot):
    from services.document_reader import read_document
    try:
        text = await read_document(message.document, bot)
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return
    topic = message.document.file_name or "По документу"
    await state.update_data(topic=topic, raw_text=text)
    await state.set_state(PresentationStates.settings)
    data = await state.get_data()
    await message.answer(
        _settings_text(data),
        parse_mode="HTML",
        reply_markup=presentation_settings_kb(),
    )


# ─── Settings ────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "presentation:back:settings")
async def presentation_back_settings(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PresentationStates.settings)
    data = await state.get_data()
    await callback.message.answer(
        _settings_text(data),
        parse_mode="HTML",
        reply_markup=presentation_settings_kb(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "presentation:change:language")
async def presentation_change_language(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PresentationStates.choosing_language)
    await callback.message.answer("🌐 Выбери язык презентации:", reply_markup=presentation_language_kb())
    await callback.answer()


@router.callback_query(
    PresentationStates.choosing_language,
    lambda c: c.data.startswith("presentation:lang:"),
)
async def presentation_set_language(callback: CallbackQuery, state: FSMContext):
    lang = callback.data[len("presentation:lang:"):]
    await state.update_data(language=lang)
    await state.set_state(PresentationStates.settings)
    data = await state.get_data()
    await callback.message.answer(
        _settings_text(data), parse_mode="HTML", reply_markup=presentation_settings_kb()
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "presentation:change:slides")
async def presentation_change_slides(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PresentationStates.choosing_slides_count)
    await callback.message.answer(
        "📒 Выбери количество слайдов (или введи цифру от 4 до 10):",
        reply_markup=presentation_slides_kb(),
    )
    await callback.answer()


@router.callback_query(
    PresentationStates.choosing_slides_count,
    lambda c: c.data.startswith("presentation:slides:"),
)
async def presentation_set_slides(callback: CallbackQuery, state: FSMContext):
    count = int(callback.data.split(":")[-1])
    await state.update_data(slides_count=count)
    await state.set_state(PresentationStates.settings)
    data = await state.get_data()
    await callback.message.answer(
        _settings_text(data), parse_mode="HTML", reply_markup=presentation_settings_kb()
    )
    await callback.answer()


@router.message(PresentationStates.choosing_slides_count)
async def presentation_slides_custom(message: Message, state: FSMContext):
    try:
        count = int(message.text.strip())
        if not (4 <= count <= 10):
            raise ValueError
    except ValueError:
        await message.answer("⚠️ Введи цифру от 4 до 10.")
        return
    await state.update_data(slides_count=count)
    await state.set_state(PresentationStates.settings)
    data = await state.get_data()
    await message.answer(
        _settings_text(data), parse_mode="HTML", reply_markup=presentation_settings_kb()
    )


@router.callback_query(lambda c: c.data == "presentation:change:design")
async def presentation_change_design(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PresentationStates.choosing_design)
    await callback.message.answer("🎨 Выбери стиль дизайна:", reply_markup=presentation_design_kb())
    await callback.answer()


@router.callback_query(
    PresentationStates.choosing_design,
    lambda c: c.data.startswith("presentation:design:"),
)
async def presentation_set_design(callback: CallbackQuery, state: FSMContext):
    design = callback.data[len("presentation:design:"):]
    await state.update_data(design=design)
    await state.set_state(PresentationStates.settings)
    data = await state.get_data()
    await callback.message.answer(
        _settings_text(data), parse_mode="HTML", reply_markup=presentation_settings_kb()
    )
    await callback.answer()


# ─── Generate ────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "presentation:generate:confirm")
async def presentation_generate(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return

    data = await state.get_data()
    await state.set_state(PresentationStates.generating)

    msg = await callback.message.answer(
        "⏳ Генерирую презентацию через Fibonacci AI...\n"
        "Это может занять до 1–2 минут, подожди 🙏"
    )

    try:
        files = await create_presentation(
            topic=data.get("topic", "Презентация"),
            language=data.get("language", "Русский"),
            slides_count=data.get("slides_count", 8),
            design=data.get("design", "Стандартный"),
        )
        await deduct_generation(db, callback.from_user.id)
        await msg.delete()

        await callback.message.answer("✅ <b>Презентация готова!</b>", parse_mode="HTML")

        if files.get("pdf") and __import__("os").path.exists(files["pdf"]):
            await callback.message.answer_document(
                FSInputFile(files["pdf"]), caption="📄 Презентация (PDF)"
            )
        if files.get("pptx") and __import__("os").path.exists(files["pptx"]):
            await callback.message.answer_document(
                FSInputFile(files["pptx"]),
                caption="📊 Презентация (PPTX)",
                reply_markup=after_presentation_kb(),
            )

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка при генерации презентации: {e}\n\nПопробуй ещё раз.")

    await callback.answer()


# ─── Follow-up from presentation ─────────────────────────────

@router.callback_query(lambda c: c.data == "followup:presentation:speech")
async def presentation_followup_speech(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return
    data = await state.get_data()
    topic = data.get("topic", "")
    if not topic:
        await callback.message.answer("❌ Не найдена тема. Начни заново.")
        await callback.answer()
        return
    from handlers.report import _generate_speech
    await _generate_speech(callback, db, f"Тема презентации: {topic}")
    await callback.answer()


@router.callback_query(lambda c: c.data == "followup:presentation:qa")
async def presentation_followup_qa(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return
    data = await state.get_data()
    topic = data.get("topic", "")
    if not topic:
        await callback.message.answer("❌ Не найдена тема. Начни заново.")
        await callback.answer()
        return
    from handlers.report import _generate_qa
    await _generate_qa(callback, db, f"Тема презентации: {topic}")
    await callback.answer()
