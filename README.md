# 📚 Учебный Telegram-бот

AI-помощник для генерации учебных материалов: доклады, рефераты, презентации, источники, речь и Q&A.

## Быстрый старт

### 1. Клонируй и установи зависимости

```bash
git clone <repo>
cd telegram_study_bot
pip install -r requirements.txt
```

### 2. Настрой переменные окружения

```bash
cp .env.example .env
# Отредактируй .env — минимум нужен TG_BOT_API_KEY
```

| Переменная | Описание | Обязательно |
|---|---|---|
| `TG_BOT_API_KEY` | Токен Telegram-бота от @BotFather | ✅ |
| `OPENAI_API_KEY` | Ключ OpenAI (или совместимого API) | Рекомендуется |
| `LLM_MODEL` | Модель LLM, по умолчанию `gpt-4o-mini` | — |
| `FIBONACCI_API_KEY` | Ключ Fibonacci AI для презентаций | Для презентаций |
| `FIBONACCI_API_URL` | URL Fibonacci API | Для презентаций |
| `YOOKASSA_SHOP_ID` | ID магазина YooKassa | Для оплат |
| `YOOKASSA_SECRET_KEY` | Секретный ключ YooKassa | Для оплат |

### 3. Запусти бота

```bash
python bot.py
```

## Деплой на Railway

1. Подключи репозиторий в Railway
2. Добавь переменные окружения через Railway Dashboard → Variables
3. Railway автоматически запустит `python bot.py` (через Procfile)
4. Используй тип сервиса **Worker** (не Web)

## Архитектура

```
telegram_study_bot/
├── bot.py                  # Точка входа, dispatcher, middleware
├── config.py               # Конфиг из .env
├── database.py             # SQLAlchemy engine + init_db
├── models.py               # ORM-модели (User, Generation, Payment)
├── keyboards.py            # Все InlineKeyboard
├── states.py               # FSM-состояния
├── prompts.py              # Все промпты для LLM
├── handlers/
│   ├── start.py            # /start и главное меню
│   ├── report.py           # Доклад
│   ├── abstract.py         # Реферат
│   ├── presentation.py     # Презентация (Fibonacci API)
│   ├── sources.py          # Источники
│   ├── tariffs.py          # Тарифы, оплата, настройки
│   └── common.py           # Общие утилиты: баланс, создание юзера
└── services/
    ├── llm.py              # Вызов LLM API
    ├── fibonacci_api.py    # Fibonacci AI для презентаций
    ├── payments.py         # YooKassa
    ├── file_generator.py   # Генерация PDF
    └── document_reader.py  # Чтение .txt и .docx
```

## Режим заглушки (разработка без ключей)

Бот работает и без реальных API-ключей:
- Без `OPENAI_API_KEY` → LLM возвращает демо-текст
- Без `FIBONACCI_API_KEY` → возвращаются тестовые PDF/PPTX-файлы
- Без `YOOKASSA_*` → тариф активируется сразу (без реального платежа)

## Тарифы

Настраиваются в `config.py` в переменной `TARIFFS`.

## Подключение другого LLM

Замени `services/llm.py`: функция `generate_text(prompt, max_tokens)` должна возвращать строку.
Совместима с любым OpenAI-совместимым API (Anthropic, Mistral, local Ollama и т.д.).


### Проверка целостности перед деплоем

Если бот не стартует из-за синтаксической ошибки в `services/sources_pipeline.py` (например, `IndentationError` или случайно попавшие строки git-diff), запустите:

```bash
python scripts/validate_sources_pipeline.py
python -m py_compile services/sources_pipeline.py handlers/sources.py bot.py
```

