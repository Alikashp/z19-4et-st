from pathlib import Path
from docx import Document as DocxDocument

MAX_FILE_SIZE = 110 * 1024
SUPPORTED_EXTENSIONS = {".txt", ".docx"}


async def validate_document(file_name: str, file_size: int | None) -> tuple[bool, str]:
    ext = Path(file_name).suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        return False, "Пока я принимаю только .txt и .docx."

    if file_size and file_size > MAX_FILE_SIZE:
        return False, "Файл слишком большой. Загрузите документ до 110 КБ или вставьте текст сообщением."

    return True, ""


def read_document(path: str) -> str:
    ext = Path(path).suffix.lower()

    if ext == ".txt":
        return Path(path).read_text(encoding="utf-8", errors="ignore")

    if ext == ".docx":
        doc = DocxDocument(path)
        return "\n".join(
            paragraph.text
            for paragraph in doc.paragraphs
            if paragraph.text.strip()
        )

    raise ValueError("Неподдерживаемый формат документа")
