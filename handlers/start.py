from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.common import get_or_create_user
from states import ReportStates, AbstractStates, SourcesStates
from keyboards import (
    main_menu_kb,
    main_reply_menu,
    input_type_kb,
    fibonacci_redirect_kb,
    sources_variant_kb,
    tariffs_kb,
)

router = Router()

START_TEXT = (
    "👋 Привет! Я помогу подготовить учебный материал:\n"
    "доклад, реферат, презентацию или список источников.\n\n"
    "Выбери, что хочешь сделать 👇"
)


@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession, state: FSMContext):
    await state.clear()
    await get_or_create_user(db, message)

    await message.answer(START_TEXT, reply_markup=main_reply_menu())
    await message.answer(
        "Также можешь выбрать действие кнопками ниже 👇",
        reply_markup=main_menu_kb()
    )


@router.callback_query(lambda c: c.data == "menu:main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    await callback.message.answer(START_TEXT, reply_markup=main_reply_menu())
    await callback.message.answer(
        "Также можешь выбрать действие кнопками ниже 👇",
        reply_markup=main_menu_kb()
    )

    await callback.answer()


@router.message(F.text == "📝 Сделать доклад")
async def reply_menu_report(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ReportStates.choosing_input_type)

    await message.answer(
        "📝 <b>Доклад</b>\n\nВыбери вариант создания:",
        parse_mode="HTML",
        reply_markup=input_type_kb("report")
    )


@router.message(F.text == "📚 Сделать реферат")
async def reply_menu_abstract(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AbstractStates.choosing_input_type)

    await message.answer(
        "📚 <b>Реферат</b>\n\nВыбери вариант создания:",
        parse_mode="HTML",
        reply_markup=input_type_kb("abstract")
    )


@router.message(F.text == "📊 Сделать презентацию")
async def reply_menu_presentation(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Создавай лучшие презентации в боте Fibonacci AI @Fibonacci_presentation_bot",
        parse_mode="HTML",
        reply_markup=fibonacci_redirect_kb()
    )


@router.message(F.text == "🔗 Оформить источники")
async def reply_menu_sources(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(SourcesStates.choosing_variant)

    await message.answer(
        "🔗 <b>Оформление источников</b>\n\nВыбери вариант:",
        parse_mode="HTML",
        reply_markup=sources_variant_kb()
    )


@router.message(F.text == "💳 Тарифы")
async def reply_menu_tariffs(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Выберите тариф для генерации учебных материалов",
        reply_markup=tariffs_kb()
    )


@router.message(F.text == "⚙️ Настройки")
async def reply_menu_settings(message: Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "⚙️ Настройки\n\nПока доступен язык по умолчанию: Русский.",
        reply_markup=main_menu_kb()
    )
