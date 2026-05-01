from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import TARIFFS
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def main_reply_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📝 Сделать доклад"),
                KeyboardButton(text="📚 Сделать реферат"),
            ],
            [
                KeyboardButton(text="📊 Сделать презентацию"),
                KeyboardButton(text="🔗 Оформить источники"),
            ],
            [
                KeyboardButton(text="💳 Тарифы"),
                KeyboardButton(text="⚙️ Настройки"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери действие 👇"
    )

# ───────────────────────── MAIN MENU ─────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 Сделать доклад", callback_data="menu:report"),
        InlineKeyboardButton(text="📚 Сделать реферат", callback_data="menu:abstract"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Сделать презентацию", callback_data="menu:presentation"),
        InlineKeyboardButton(text="🔗 Оформить источники", callback_data="menu:sources"),
    )
    builder.row(
        InlineKeyboardButton(text="💳 Тарифы", callback_data="menu:tariffs"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
    )
    return builder.as_markup()


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main")]
    ])


# ───────────────────────── REPORT / ABSTRACT ─────────────────────────

def input_type_kb(material: str) -> InlineKeyboardMarkup:
    """material: 'report' or 'abstract'"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✍️ По теме", callback_data=f"{material}:input:topic"),
        InlineKeyboardButton(text="📄 По тексту", callback_data=f"{material}:input:text"),
    )
    if material == "report":
        builder.row(
            InlineKeyboardButton(text="📎 По документу", callback_data=f"{material}:input:document"),
        )
    builder.row(
        InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"),
    )
    return builder.as_markup()


def level_kb(material: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏫 Школа", callback_data=f"{material}:level:school"),
        InlineKeyboardButton(text="🎓 Колледж / СПО", callback_data=f"{material}:level:college"),
        InlineKeyboardButton(text="🏛 Вуз", callback_data=f"{material}:level:university"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def volume_kb(material: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if material == "report":
        volumes = [("1–2 страницы", "1-2"), ("3–5 страниц", "3-5"), ("Сам реши", "auto")]
    else:
        volumes = [
            ("1–3 страницы", "1-3"), ("5–7 страниц", "5-7"),
            ("8–10 страниц", "8-10"), ("Сам реши", "auto")
        ]
    buttons = [InlineKeyboardButton(text=label, callback_data=f"{material}:volume:{val}") for label, val in volumes]
    builder.row(*buttons)
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def confirm_generation_kb(material: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Сгенерировать", callback_data=f"{material}:generate:confirm"),
        InlineKeyboardButton(text="✏️ Изменить параметры", callback_data=f"{material}:generate:edit"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def after_report_kb(material_text: str, material_data: str) -> InlineKeyboardMarkup:
    """Кнопки после генерации доклада/реферата"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Сделать презентацию", callback_data=f"followup:{material_data}:presentation"),
        InlineKeyboardButton(text="🎤 Сделать речь", callback_data=f"followup:{material_data}:speech"),
    )
    builder.row(
        InlineKeyboardButton(text="❓ Вопросы и ответы", callback_data=f"followup:{material_data}:qa"),
        InlineKeyboardButton(text="🔗 Оформить источники", callback_data="menu:sources"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def after_speech_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❓ Подготовить вопросы и ответы", callback_data="followup:speech:qa"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def after_qa_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎤 Сделать речь для выступления", callback_data="followup:qa:speech"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


# ───────────────────────── PRESENTATION ─────────────────────────

PRESENTATION_LANGUAGES = [
    "Русский", "English", "Қазақша", "O'zbek", "中文",
    "Español", "हिन्दी", "Português", "العربية", "Français",
    "日本語", "Deutsch", "한국어", "Bahasa Indonesia",
]

PRESENTATION_DESIGNS = ["Стандартный", "Стильный", "Креативный"]


def presentation_input_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✍️ По теме", callback_data="presentation:input:topic"),
        InlineKeyboardButton(text="📄 По тексту", callback_data="presentation:input:text"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def presentation_settings_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🌐 Сменить язык", callback_data="presentation:change:language"),
        InlineKeyboardButton(text="📒 Сменить кол-во слайдов", callback_data="presentation:change:slides"),
    )
    builder.row(
        InlineKeyboardButton(text="🎨 Сменить дизайн", callback_data="presentation:change:design"),
        InlineKeyboardButton(text="✅ Сгенерировать презентацию", callback_data="presentation:generate:confirm"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def presentation_language_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for lang in PRESENTATION_LANGUAGES:
        builder.add(InlineKeyboardButton(text=lang, callback_data=f"presentation:lang:{lang}"))
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="presentation:back:settings"))
    return builder.as_markup()


def presentation_slides_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for count in [4, 6, 8, 10]:
        builder.add(InlineKeyboardButton(text=str(count), callback_data=f"presentation:slides:{count}"))
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="presentation:back:settings"))
    return builder.as_markup()


def presentation_design_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for design in PRESENTATION_DESIGNS:
        builder.add(InlineKeyboardButton(text=design, callback_data=f"presentation:design:{design}"))
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="presentation:back:settings"))
    return builder.as_markup()


def after_presentation_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎤 Сделать речь для выступления", callback_data="followup:presentation:speech"),
        InlineKeyboardButton(text="❓ Вопросы и ответы", callback_data="followup:presentation:qa"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


# ───────────────────────── SOURCES ─────────────────────────

def sources_variant_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подобрать по теме", callback_data="sources:variant:topic"),
        InlineKeyboardButton(text="🔗 Оформить свои", callback_data="sources:variant:own"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def sources_format_kb(prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 ГОСТ", callback_data=f"{prefix}:format:ГОСТ"),
        InlineKeyboardButton(text="📋 APA 7", callback_data=f"{prefix}:format:APA7"),
        InlineKeyboardButton(text="❓ В чём отличие?", callback_data=f"{prefix}:format:diff"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def sources_count_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for label, val in [("3–5", "3-5"), ("5–7", "5-7"), ("7–10", "7-10"), ("10–15", "10-15")]:
        builder.add(InlineKeyboardButton(text=label, callback_data=f"sources:count:{val}"))
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def after_sources_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


# ───────────────────────── TARIFFS ─────────────────────────

def tariffs_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, tariff in enumerate(TARIFFS):
        builder.row(
            InlineKeyboardButton(
                text=f"💳 {tariff['label']}",
                callback_data=f"pay:tariff:{i}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()


def no_balance_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="menu:tariffs"))
    builder.row(InlineKeyboardButton(text="⬅️ Вернуться в главное меню", callback_data="menu:main"))
    return builder.as_markup()
