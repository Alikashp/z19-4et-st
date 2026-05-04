import os
import re

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from states import ReportStates
from keyboards import (
    input_type_kb,
    level_kb,
    volume_kb,
    confirm_generation_kb,
    after_report_kb,
    main_menu_kb,
)
from prompts import report_prompt, LEVEL_LABELS, VOLUME_LABELS
from services.llm import generate_text
from services.file_generator import generate_pdf, get_preview
from services.document_reader import read_document
from handlers.common import check_balance, deduct_generation


router = Router()
MATERIAL = "report"

LAST_TEXT_DIR = "generated_files"


def _save_last_material(user_id: int, text: str):
    os.makedirs(LAST_TEXT_DIR, exist_ok=True)
    path = os.path.join(LAST_TEXT_DIR, f"last_report_{user_id}.txt")

    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _load_last_material(user_id: int) -> str:
    path = os.path.join(LAST_TEXT_DIR, f"last_report_{user_id}.txt")

    if not os.path.exists(path):
        return ""

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _strip_markdown_stars(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", text, flags=re.DOTALL)
    cleaned = re.sub(r"\*(.*?)\*", r"\1", cleaned, flags=re.DOTALL)
    return cleaned


# ─── Entry ───────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "menu:report")
async def report_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(ReportStates.choosing_input_type)

    await callback.message.answer(
        "📝 <b>Доклад</b>\n\nВыбери вариант создания:",
        parse_mode="HTML",
        reply_markup=input_type_kb(MATERIAL),
    )

    await callback.answer()


# ─── Input type ──────────────────────────────────────────────

@router.callback_query(
    ReportStates.choosing_input_type,
    lambda c: c.data.startswith("report:input:")
)
async def report_input_type(callback: CallbackQuery, state: FSMContext):
    input_type = callback.data.split(":")[-1]
    await state.update_data(input_type=input_type)

    if input_type == "topic":
        await state.set_state(ReportStates.waiting_for_topic)
        await callback.message.answer("✍️ Введи тему доклада:")

    elif input_type == "text":
        await state.set_state(ReportStates.waiting_for_text)
        await callback.message.answer(
            "📄 Отправь текст, на основе которого нужно подготовить доклад:"
        )

    elif input_type == "document":
        await state.set_state(ReportStates.waiting_for_document)
        await callback.message.answer(
            "📎 Отправь документ с расширением <b>.txt</b> или <b>.docx</b> "
            "и размером не более 110 КБ.",
            parse_mode="HTML",
        )

    await callback.answer()


# ─── Getting source material ─────────────────────────────────

@router.message(ReportStates.waiting_for_topic, F.document)
async def report_document_sent_in_topic_mode(message: Message):
    await message.answer(
        "📎 Вы отправили документ, но сейчас бот ждёт короткую тему текстом.\n\n"
        "Например: «Экономика предприятия».\n\n"
        "Для работы с файлом выбери режим:\n"
        "📝 Сделать доклад → 📎 По документу.",
        reply_markup=main_menu_kb(),
    )


@router.message(ReportStates.waiting_for_topic, F.text)
async def report_got_topic(message: Message, state: FSMContext):
    topic = (message.text or "").strip()

    if len(topic) > 200:
        await message.answer(
            "Похоже, вы вставили не тему, а большой текст.\n\n"
            "Для темы нужно коротко: до 200 символов.\n"
            "Например: «Инновации и инвестиции на зарубежных рынках».\n\n"
            "Если хочешь сделать доклад по большому тексту, вернись назад и выбери режим «По тексту».",
            reply_markup=main_menu_kb(),
        )
        return

    if len(topic) < 5:
        await message.answer(
            "Тема слишком короткая. Напиши чуть подробнее.\n\n"
            "Например: «Управление требованиями стейкхолдеров в ИТ-стартапе».",
            reply_markup=main_menu_kb(),
        )
        return

    await state.update_data(
        topic=topic,
        material_text=topic,
    )

    await state.set_state(ReportStates.choosing_level)

    await message.answer(
        "🎓 Выбери уровень подготовки:",
        reply_markup=level_kb(MATERIAL),
    )

    await state.set_state(ReportStates.choosing_level)

    await message.answer(
        "🎓 Выбери уровень подготовки:",
        reply_markup=level_kb(MATERIAL),
    )


@router.message(ReportStates.waiting_for_text, F.document)
async def report_document_sent_in_text_mode(message: Message):
    await message.answer(
        "📎 Вы отправили документ, но выбрала режим «По тексту».\n\n"
        "Если хотите сделать доклад по файлу, вернитесь в главное меню и выберите:\n"
        "📝 Сделать доклад → 📎 По документу.\n\n"
        "Или просто скопируйте текст из документа и отправьте его сообщением.",
        reply_markup=main_menu_kb(),
    )


@router.message(ReportStates.waiting_for_text, F.text)
async def report_got_text(message: Message, state: FSMContext):
    source_text = (message.text or "").strip()

    if len(source_text) < 200:
        await message.answer(
            "Текст слишком короткий для режима «По тексту».\n\n"
            "Если у тебя просто тема, вернись назад и выбери режим «По теме».\n"
            "Если это текст, пришли более полный фрагмент — хотя бы 200 символов.",
            reply_markup=main_menu_kb(),
        )
        return

    await state.update_data(
        topic="(из текста)",
        material_text=source_text,
    )

    await state.set_state(ReportStates.choosing_level)

    await message.answer(
        "🎓 Выбери уровень подготовки:",
        reply_markup=level_kb(MATERIAL),
    )

    await state.set_state(ReportStates.choosing_level)

    await message.answer(
        "🎓 Выбери уровень подготовки:",
        reply_markup=level_kb(MATERIAL),
    )


@router.message(ReportStates.waiting_for_document, F.text)
async def report_text_sent_in_document_mode(message: Message):
    await message.answer(
        "📄 Вы отправили текст, но выбрали режим «По документу».\n\n"
        "Если хотите сделать доклад по тексту, вернитесь в главное меню и выберите:\n"
        "📝 Сделать доклад → 📄 По тексту.\n\n"
        "Или отправьте файл в формате .txt или .docx.",
        reply_markup=main_menu_kb(),
    )


@router.message(ReportStates.waiting_for_document, F.document)
async def report_got_document(message: Message, state: FSMContext, bot: Bot):
    try:
        text = await read_document(message.document, bot)

    except ValueError as e:
        await message.answer(f"❌ {e}")
        return

    await state.update_data(
        topic="(из документа)",
        material_text=text,
    )

    await state.set_state(ReportStates.choosing_level)

    await message.answer(
        "🎓 Выбери уровень подготовки:",
        reply_markup=level_kb(MATERIAL),
    )


# ─── Level ───────────────────────────────────────────────────

@router.callback_query(
    ReportStates.choosing_level,
    lambda c: c.data.startswith("report:level:")
)
async def report_level(callback: CallbackQuery, state: FSMContext):
    level = callback.data.split(":")[-1]

    await state.update_data(level=level)
    await state.set_state(ReportStates.choosing_volume)

    await callback.message.answer(
        "📏 Выбери объём:",
        reply_markup=volume_kb(MATERIAL),
    )

    await callback.answer()


# ─── Volume ──────────────────────────────────────────────────

@router.callback_query(
    ReportStates.choosing_volume,
    lambda c: c.data.startswith("report:volume:")
)
async def report_volume(callback: CallbackQuery, state: FSMContext):
    volume = callback.data.split(":")[-1]

    await state.update_data(volume=volume)
    data = await state.get_data()

    level_label = LEVEL_LABELS.get(data.get("level"), data.get("level"))
    volume_label = VOLUME_LABELS.get(volume, volume)

    text = (
        f"📋 <b>Проверь параметры перед генерацией:</b>\n\n"
        f"📌 Тема: <b>{data.get('topic', '—')}</b>\n"
        f"🎓 Уровень: <b>{level_label}</b>\n"
        f"📏 Объём: <b>{volume_label}</b>"
    )

    await state.set_state(ReportStates.confirming)

    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=confirm_generation_kb(MATERIAL),
    )

    await callback.answer()


# ─── Confirm ─────────────────────────────────────────────────

@router.callback_query(
    ReportStates.confirming,
    lambda c: c.data == "report:generate:edit"
)
async def report_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ReportStates.choosing_input_type)

    await callback.message.answer(
        "Выбери вариант создания:",
        reply_markup=input_type_kb(MATERIAL),
    )

    await callback.answer()


@router.callback_query(
    ReportStates.confirming,
    lambda c: c.data == "report:generate:confirm"
)
async def report_generate(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return

    data = await state.get_data()

    await state.set_state(ReportStates.generating)

    msg = await callback.message.answer(
        "⏳ Генерирую доклад, подожди немного..."
    )

    try:
        prompt = report_prompt(
            topic=data.get("material_text") or data.get("topic", ""),
            level=data.get("level", "school"),
            volume=data.get("volume", "auto"),
        )

        full_text = _strip_markdown_stars(await generate_text(prompt, max_tokens=4000))

        await state.update_data(generated_text=full_text)
        _save_last_material(callback.from_user.id, full_text)

        safe_topic = (
            data.get("topic") or "doklad"
        )[:30].replace(" ", "_").replace("/", "_")

        pdf_filename = f"report_{callback.from_user.id}_{safe_topic}.pdf"
        pdf_path = generate_pdf(full_text, pdf_filename)

        preview = get_preview(full_text, lines=3)

        await deduct_generation(db, callback.from_user.id)

        await msg.delete()

        await callback.message.answer(
            f"✅ <b>Доклад готов!</b>\n\n"
            f"{preview}\n\n"
            f"<i>...полный текст в файле ниже 👇</i>",
            parse_mode="HTML",
        )

        await callback.message.answer_document(
            FSInputFile(pdf_path),
            caption="📄 Полный доклад",
            reply_markup=after_report_kb("доклад", MATERIAL),
        )

    except Exception as e:
        await msg.edit_text(
            f"❌ Ошибка при генерации: {e}\n\nПопробуй ещё раз."
        )

    await callback.answer()


# ─── Follow-up: Speech and Q&A ───────────────────────────────

@router.callback_query(lambda c: c.data == f"followup:{MATERIAL}:speech")
async def report_followup_speech(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return

    data = await state.get_data()
    material_text = data.get("generated_text") or _load_last_material(callback.from_user.id)

    if not material_text:
        await callback.message.answer(
            "❌ Не найден материал для генерации речи. Начни заново."
        )
        await callback.answer()
        return

    await _generate_speech(callback, db, material_text)

    await callback.answer()


@router.callback_query(lambda c: c.data == f"followup:{MATERIAL}:qa")
async def report_followup_qa(
    callback: CallbackQuery,
    state: FSMContext,
    db: AsyncSession,
):
    if not await check_balance(db, callback.from_user.id, callback=callback):
        await callback.answer()
        return

    data = await state.get_data()
    material_text = data.get("generated_text") or _load_last_material(callback.from_user.id)

    if not material_text:
        await callback.message.answer(
            "❌ Не найден материал. Начни заново."
        )
        await callback.answer()
        return

    await _generate_qa(callback, db, material_text)

    await callback.answer()


async def _generate_speech(
    callback: CallbackQuery,
    db: AsyncSession,
    material_text: str,
):
    from prompts import speech_prompt
    from keyboards import after_speech_kb

    msg = await callback.message.answer(
        "⏳ Готовлю речь для выступления..."
    )

    try:
        prompt = speech_prompt(material_text[:3000])
        result = _strip_markdown_stars(await generate_text(prompt, max_tokens=1000))

        await deduct_generation(db, callback.from_user.id)

        await msg.delete()

        await callback.message.answer(
            f"🎤 <b>Речь для выступления:</b>\n\n{result}",
            parse_mode="HTML",
            reply_markup=after_speech_kb(),
        )

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


async def _generate_qa(
    callback: CallbackQuery,
    db: AsyncSession,
    material_text: str,
):
    from prompts import qa_prompt
    from keyboards import after_qa_kb

    msg = await callback.message.answer(
        "⏳ Готовлю вопросы и ответы..."
    )

    try:
        prompt = qa_prompt(material_text[:3000])
        result = _strip_markdown_stars(await generate_text(prompt, max_tokens=1000))

        await deduct_generation(db, callback.from_user.id)

        await msg.delete()

        await callback.message.answer(
            f"❓ <b>Вопросы и ответы:</b>\n\n{result}",
            parse_mode="HTML",
            reply_markup=after_qa_kb(),
        )

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")
