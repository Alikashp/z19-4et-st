import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import aiofiles


OUTPUT_DIR = "generated_files"


def _ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def _register_fonts():
    """Регистрирует шрифт с поддержкой кириллицы."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CyrillicFont", path))
                return "CyrillicFont"
            except Exception as e:
                print(f"Font register error for {path}: {e}")
                continue

    raise RuntimeError(
        "Не найден шрифт с поддержкой кириллицы. "
        "Установи fonts-dejavu-core на сервере."
    )


def generate_pdf(text: str, filename: str) -> str:
    """Генерирует PDF из текста. Возвращает путь к файлу."""
    _ensure_output_dir()
    path = os.path.join(OUTPUT_DIR, filename)

    font_name = _register_fonts()

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    normal_style = ParagraphStyle(
        "Normal_Cyrillic",
        fontName=font_name,
        fontSize=12,
        leading=18,
        alignment=TA_LEFT,
        spaceAfter=8,
    )
    heading_style = ParagraphStyle(
        "Heading_Cyrillic",
        fontName=font_name,
        fontSize=14,
        leading=20,
        alignment=TA_LEFT,
        spaceAfter=12,
        spaceBefore=16,
        textColor="#1a1a2e",
    )

    story = []
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            story.append(Spacer(1, 6))
            continue

        # Определяем заголовки по markdown-синтаксису
        if line.startswith("## "):
            para = Paragraph(line[3:], heading_style)
        elif line.startswith("# "):
            para = Paragraph(line[2:], heading_style)
        else:
            # Экранируем HTML-символы для ReportLab
            safe_line = (
                line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
            )
            para = Paragraph(safe_line, normal_style)

        story.append(para)

    doc.build(story)
    return path


def get_preview(text: str, lines: int = 3) -> str:
    """Возвращает первые N непустых строк текста."""
    result = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            result.append(stripped)
        if len(result) >= lines:
            break
    return "\n".join(result)
