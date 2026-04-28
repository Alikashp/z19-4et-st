import os
from dotenv import load_dotenv

load_dotenv()

TG_BOT_API_KEY = os.getenv("TG_BOT_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
FIBONACCI_API_KEY = os.getenv("FIBONACCI_API_KEY", "")
FIBONACCI_API_URL = os.getenv("FIBONACCI_API_URL", "https://api.fibonacci.ai/v1")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
PAYMENT_PROVIDER = os.getenv("PAYMENT_PROVIDER", "yookassa")

DATABASE_URL = "sqlite+aiosqlite:///./study_bot.db"

# Tariffs config
TARIFFS = [
    {
        "name": "Старт",
        "generations": 3,
        "price": 99,
        "label": "3 генерации — 99 ₽",
        "description": "Попробуй и убедись в качестве",
    },
    {
        "name": "Студент",
        "generations": 10,
        "price": 249,
        "label": "10 генераций — 249 ₽",
        "description": "Оптимальный выбор для студента",
    },
    {
        "name": "Про",
        "generations": 30,
        "price": 599,
        "label": "30 генераций — 599 ₽",
        "description": "Максимум для активной учёбы",
    },
]
