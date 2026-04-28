from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from handlers.common import get_or_create_user
from keyboards import main_menu_kb

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
    await message.answer(START_TEXT, reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "menu:main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(START_TEXT, reply_markup=main_menu_kb())
    await callback.answer()
