import os
import re
from html import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT


OUTPUT_DIR = "generated_files"


def _ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def _register_fonts():
    """Регистрирует шрифты с поддержкой кириллицы."""
    regular_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]

    regular_font_path = None
    bold_font_path = None

    for path in regular_paths:
        if os.path.exists(path):
            regular_font_path = path
            break

    for path in bold_paths:
        if os.path.exists(path):
            bold_font_path = path
            break

    if not regular_font_path:
        raise RuntimeError(
            "Не найден шрифт с поддержкой кириллицы. "
            "Установи fonts-dejavu-core на сервере."
        )

    pdfmetrics.registerFont(TTFont("CyrillicFont", regular_font_path))

    if bold_font_path:
        pdfmetrics.registerFont(TTFont("CyrillicFont-Bold", bold_font_path))
    else:
        pdfmetrics.registerFont(TTFont("CyrillicFont-Bold", regular_font_path))

    return "CyrillicFont"


def _markdown_to_html(line: str) -> str:
    """
    Минимально переводит Markdown в HTML, который понимает ReportLab:
    **жирный** -> <b>жирный</b>
    """
    safe_line = escape(line)

    safe_line = re.sub(
        r"\*\*(.+?)\*\*",
        r"<b>\1</b>",
        safe_line
    )

    safe_line = re.sub(
        r"\*(.+?)\*",
        r"<i>\1</i>",
        safe_line
    )

    return safe_line


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

    normal_style = ParagraphStyle(
        "Normal_Cyrillic",
        fontName=font_name,
        fontSize=12,
        leading=18,
        alignment=TA_LEFT,
        spaceAfter=8,
    )

    heading_1_style = ParagraphStyle(
        "Heading1_Cyrillic",
        fontName="CyrillicFont-Bold",
        fontSize=16,
        leading=22,
        alignment=TA_LEFT,
        spaceAfter=12,
        spaceBefore=14,
    )

    heading_2_style = ParagraphStyle(
        "Heading2_Cyrillic",
        fontName="CyrillicFont-Bold",
        fontSize=14,
        leading=20,
        alignment=TA_LEFT,
        spaceAfter=10,
        spaceBefore=12,
    )

    heading_3_style = ParagraphStyle(
        "Heading3_Cyrillic",
        fontName="CyrillicFont-Bold",
        fontSize=13,
        leading=19,
        alignment=TA_LEFT,
        spaceAfter=8,
        spaceBefore=10,
    )

    story = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()

        if not line:
            story.append(Spacer(1, 6))
            continue

        if line.startswith("### "):
            story.append(Paragraph(_markdown_to_html(line[4:]), heading_3_style))

        elif line.startswith("## "):
            story.append(Paragraph(_markdown_to_html(line[3:]), heading_2_style))

        elif line.startswith("# "):
            story.append(Paragraph(_markdown_to_html(line[2:]), heading_1_style))

        elif line.startswith("- "):
            bullet_text = "• " + line[2:]
            story.append(Paragraph(_markdown_to_html(bullet_text), normal_style))

        else:
            story.append(Paragraph(_markdown_to_html(line), normal_style))

    doc.build(story)
    return path


def get_preview(text: str, lines: int = 3) -> str:
    """Возвращает первые N непустых строк текста."""
    result = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            clean = (
                stripped
                .replace("### ", "")
                .replace("## ", "")
                .replace("# ", "")
                .replace("**", "")
            )
            result.append(clean)
        if len(result) >= lines:
            break
    return "\n".join(result)
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
