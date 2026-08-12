"""Active PDF layout: text report plus one compact natal-data page.

The former implementation remains in services.reports as an unused archive.
"""
from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PAPER = colors.HexColor("#F3E9D8")
INK = colors.HexColor("#17130F")
NAVY = colors.HexColor("#17130F")
MUTED = colors.HexColor("#3D3731")
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

for regular_path, bold_path in (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
):
    if Path(regular_path).exists() and Path(bold_path).exists():
        pdfmetrics.registerFont(TTFont("ReportFont", regular_path))
        pdfmetrics.registerFont(TTFont("ReportFont-Bold", bold_path))
        FONT = "ReportFont"
        FONT_BOLD = "ReportFont-Bold"
        break


def _load_sections() -> dict[str, list[tuple[str, str]]]:
    """Use the active section-hint index as the single section catalog."""
    index_path = Path(__file__).resolve().parent.parent / "section_hints" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    sections: dict[str, list[tuple[str, str]]] = {}
    for item in index["sections"]:
        path = index_path.parent / item["path"]
        data = json.loads(path.read_text(encoding="utf-8"))
        sections.setdefault(item["report_type"], []).append(
            (item["title_ru"], data.get("brief", ""))
        )
    return sections


SECTIONS = _load_sections()


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _draw_background(canvas, doc) -> None:
    """Draw a clean page without the old footer or page number."""
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.restoreState()


def _table(rows: list[list[str]], col_widths: list[float], body: ParagraphStyle) -> Table:
    rendered = [[_paragraph(value, body) for value in row] for row in rows]
    table = Table(rendered, colWidths=col_widths, repeatRows=1, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5D8C4")),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#8E8478")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
    ]))
    return table


def _natal_table(chart: dict, body: ParagraphStyle) -> Table:
    rows = [["Планета", "Знак", "Градус", "Дом"]]
    for name, position in chart["planets"].items():
        rows.append([
            name,
            position["sign"],
            f"{position['degree']:.1f}°",
            str(position["house"]),
        ])
    return _table(rows, [42 * mm, 42 * mm, 32 * mm, 28 * mm], body)


def _houses_table(chart: dict, body: ParagraphStyle) -> Table:
    zodiac = (
        "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
        "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы",
    )
    rows = [["Дом", "Куспид", "Знак"]]
    for number, longitude in enumerate(chart["houses"], start=1):
        rows.append([
            str(number),
            f"{longitude % 30:.1f}°",
            zodiac[int(longitude // 30) % 12],
        ])
    return _table(rows, [35 * mm, 45 * mm, 64 * mm], body)


def generate_report(
    report_type: str,
    chart: dict,
    second_chart: dict | None,
    content: dict[str, Any],
    recipient_name: str | None = None,
    recipient_username: str | None = None,
    recipient_photo: Any | None = None,
) -> Path:
    """Create the simplified active report layout."""
    if not content:
        raise ValueError("PDF нельзя сформировать без проверенного текста.")
    if report_type not in SECTIONS:
        raise ValueError(f"Неизвестный тип отчёта: {report_type}")

    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    filename = output_dir / f"astro_{report_type}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontName=FONT_BOLD, fontSize=26,
        leading=32, alignment=TA_CENTER, textColor=NAVY, spaceAfter=7 * mm,
    )
    heading = ParagraphStyle(
        "ReportHeading", parent=styles["Heading2"], fontName=FONT_BOLD, fontSize=16,
        leading=21, textColor=NAVY, spaceBefore=4 * mm, spaceAfter=3 * mm,
    )
    body = ParagraphStyle(
        "ReportBody", parent=styles["BodyText"], fontName=FONT, fontSize=11,
        leading=17, textColor=INK, alignment=4, firstLineIndent=6 * mm, spaceAfter=3 * mm,
    )
    table_body = ParagraphStyle(
        "TableBody", parent=body, fontSize=9, leading=11, firstLineIndent=0,
        alignment=TA_CENTER, spaceAfter=0,
    )
    caption = ParagraphStyle(
        "ReportCaption", parent=body, fontSize=9, leading=12, textColor=MUTED,
        alignment=TA_CENTER, firstLineIndent=0,
    )
    type_titles = {
        "personality_free": "БЕСПЛАТНЫЙ РАЗБОР ЛИЧНОСТИ",
        "personality": "РАЗБОР ЛИЧНОСТИ",
        "love": "ЛЮБОВЬ И ОТНОШЕНИЯ",
        "compatibility": "СОВМЕСТИМОСТЬ",
        "money": "ДЕНЬГИ И РЕАЛИЗАЦИЯ",
    }

    display_name = recipient_name or "Персональный отчёт"
    if recipient_username:
        display_name = f"{display_name} · @{recipient_username}"
    story = [
        Spacer(1, 28 * mm),
        _paragraph(type_titles[report_type], title),
        _paragraph(display_name, caption),
        Spacer(1, 18 * mm),
        _paragraph(content["title"], title),
        _paragraph(content["intro"], body),
        PageBreak(),
        _paragraph("НАТАЛЬНАЯ КАРТА", heading),
        _natal_table(chart, table_body),
        Spacer(1, 5 * mm),
        _paragraph("ДОМА", heading),
        _houses_table(chart, table_body),
    ]

    generated_by_title = {section["title"]: section for section in content["sections"]}
    for title_text, _ in SECTIONS[report_type]:
        section = generated_by_title.get(title_text)
        if section is None:
            raise ValueError(f"Отсутствует раздел «{title_text}».")
        story.extend([
            PageBreak(),
            _paragraph(title_text, heading),
            _paragraph(section["content"], body),
        ])

    document = SimpleDocTemplate(
        str(filename),
        pagesize=A4,
        rightMargin=23 * mm,
        leftMargin=23 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=type_titles[report_type],
    )
    document.build(story, onFirstPage=_draw_background, onLaterPages=_draw_background)
    return filename
