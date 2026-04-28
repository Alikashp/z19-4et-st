import aiohttp
import json
from config import OPENAI_API_KEY, LLM_MODEL


async def generate_text(prompt: str, max_tokens: int = 4000) -> str:
    """
    Вызывает LLM API (OpenAI-совместимый) и возвращает сгенерированный текст.
    """
    if not OPENAI_API_KEY:
        # Заглушка для разработки без ключа
        return _stub_response(prompt)

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты — учебный помощник для школьников и студентов. "
                    "Пиши грамотно, структурированно и по существу."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"LLM API error {resp.status}: {text}")
            data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()


def _stub_response(prompt: str) -> str:
    """Заглушка — используется если OPENAI_API_KEY не задан."""
    return (
        "⚠️ РЕЖИМ ЗАГЛУШКИ: ключ LLM не настроен.\n\n"
        "Это демонстрационный ответ. В реальном режиме здесь будет "
        "сгенерированный учебный материал по вашему запросу.\n\n"
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris.\n\n"
        "## Вывод\nЭто демонстрационный текст.\n\n"
        "## Источники\n1. Демонстрационный источник — не использовать в реальной работе."
    )
