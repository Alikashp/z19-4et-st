import io
from aiogram.types import Document, Bot

MAX_SIZE_BYTES = 110 * 1024  # 110 КБ


async def read_document(document: Document, bot: Bot) -> str:
    """
    Скачивает и читает документ из Telegram.
    Поддерживает .txt и .docx.
    Возвращает текст или выбрасывает исключение.
    """
    file_name = document.file_name or ""
    file_size = document.file_size or 0

    if file_size > MAX_SIZE_BYTES:
        raise ValueError(
            f"Файл слишком большой ({file_size // 1024} КБ). "
            f"Максимальный размер — 110 КБ."
        )

    ext = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    if ext not in ("txt", "docx"):
        raise ValueError(
            f"Формат .{ext} не поддерживается. "
            f"Отправьте файл с расширением .txt или .docx."
        )

    # Скачиваем файл в память
    file = await bot.get_file(document.file_id)
    buf = io.BytesIO()
    await bot.download_file(file.file_path, destination=buf)
    buf.seek(0)

    if ext == "txt":
        raw = buf.read()
        for encoding in ("utf-8", "cp1251", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("Не удалось определить кодировку файла.")

    if ext == "docx":
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(buf)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            raise ValueError(f"Ошибка чтения .docx: {e}")

    raise ValueError("Неподдерживаемый формат.")
