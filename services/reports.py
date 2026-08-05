from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT = "Helvetica"
for font_path in (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
):
    if Path(font_path).exists():
        pdfmetrics.registerFont(TTFont("AstroFont", font_path))
        FONT = "AstroFont"
        break

SECTIONS = {
    "personality": [
        ("Введение", "как устроена натальная карта и как читать этот отчёт"),
        ("Солнечный знак", "характер, сильные и слабые стороны"),
        ("Лунный знак", "эмоции, интуиция и потребность в заботе"),
        ("Асцендент", "внешний образ и первое впечатление"),
        ("Личностные планеты", "общение, любовь и энергия"),
        ("Социальные планеты", "карьерные возможности, успех и ответственность"),
        ("Высшие планеты", "уникальные таланты и глубокие трансформации"),
        ("Дома гороскопа", "главные сферы жизни и акцентные дома"),
        ("Ключевые аспекты", "сильные стороны и основные вызовы карты"),
        ("Карьера и призвание", "сферы реализации и таланты"),
        ("Кармические задачи", "направления роста и внутренние уроки"),
        ("Любовь и отношения", "подход к любви и подходящие партнёры"),
        ("Здоровье и энергия", "бережная поддержка ресурса и восстановления"),
        ("Таланты и способности", "врождённые дары, которые стоит развивать"),
        ("Заключение", "ваша главная опора на ближайший период"),
    ],
    "compatibility": [
        ("Введение", "как устроена синастрия и что означает совместимость"),
        ("Общий обзор", "солнечные знаки партнёров и общее впечатление от союза"),
        ("Эмоциональная совместимость", "как вы чувствуете и поддерживаете друг друга"),
        ("Сексуальная совместимость", "Венера, Марс и язык желания"),
        ("Интеллектуальная совместимость", "как вы общаетесь и находите общие темы"),
        ("Бытовая совместимость", "как договариваться и распределять роли"),
        ("Кармические аспекты", "важные уроки и глубокие точки встречи"),
        ("Сильные стороны пары", "что делает отношения устойчивыми"),
        ("Слабые стороны и риски", "конфликтные точки, которые требуют внимания"),
        ("Совместимость по знакам", "дополнительный анализ стихий и солнечных знаков"),
        ("Рекомендации", "как использовать сильные стороны и улучшать отношения"),
        ("Заключение", "итоговый потенциал отношений"),
    ],
    "money": [
        ("Введение", "какие элементы карты связывают с финансовым потенциалом"),
        ("Финансовый профиль", "ваш способ создавать и удерживать деньги"),
        ("Дом денег", "отношение к личным финансам, доходу и накоплениям"),
        ("Дом работы и услуг", "сферы, в которых проще монетизироваться"),
        ("Дом инвестиций и партнёрских денег", "сотрудничество, общие ресурсы и риски"),
        ("Венера и Юпитер", "ресурсы удачи, роста и удовольствия"),
        ("Сатурн и Плутон", "ограничения и трансформации в финансовой сфере"),
        ("Аспекты к денежным домам", "сильные стороны и зоны напряжения"),
        ("Кармические установки", "убеждения, которые стоит осознать и пересмотреть"),
        ("Периоды возможностей", "общие ориентиры для подготовки и планирования"),
        ("Лучшие профессии", "сферы, в которых легче раскрыть потенциал"),
        ("Практические советы", "реалистичные действия для работы с привычками"),
        ("Заключение", "главное направление для развития финансовой устойчивости"),
    ],
}

ZODIAC_SHORT = ("Ове", "Тел", "Бли", "Рак", "Лев", "Дев", "Вес", "Ско", "Стр", "Коз", "Вод", "Рыб")


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B1D3A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#172033")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D1DD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _planet_table(chart: dict) -> Table:
    rows = [["Планета", "Знак", "Градус", "Дом"]]
    for planet, position in chart["planets"].items():
        rows.append([
            planet,
            position["sign"],
            f"{position['degree']:.1f}°",
            str(position["house"]),
        ])
    return _table(rows, [43 * mm, 42 * mm, 32 * mm, 25 * mm])


def _aspect_table(aspects: list[dict], title: str = "Аспекты") -> Table:
    rows = [[title, "Тип", "Орбис"]]
    for aspect in aspects[:20]:
        rows.append([
            f"{aspect['first']} — {aspect['second']}",
            aspect["type"],
            f"{aspect['orb']:.1f}°",
        ])
    if len(rows) == 1:
        rows.append(["Нет мажорных аспектов", "—", "—"])
    return _table(rows, [80 * mm, 42 * mm, 20 * mm])


def _natal_chart(chart: dict) -> Drawing:
    size = 150 * mm
    center = size / 2
    outer = 60 * mm
    inner = 43 * mm
    drawing = Drawing(size, size)
    drawing.add(Circle(center, center, outer, strokeColor=colors.HexColor("#0B1D3A"), strokeWidth=1.4))
    drawing.add(Circle(center, center, inner, strokeColor=colors.HexColor("#D4AF37"), strokeWidth=0.8))

    from math import cos, pi, sin

    for index, sign in enumerate(ZODIAC_SHORT):
        angle = pi / 2 - index * pi / 6
        x1, y1 = center + inner * cos(angle), center + inner * sin(angle)
        x2, y2 = center + outer * cos(angle), center + outer * sin(angle)
        drawing.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor("#C9D1DD")))
        text_angle = angle - pi / 12
        drawing.add(String(
            center + (outer - 7 * mm) * cos(text_angle),
            center + (outer - 7 * mm) * sin(text_angle),
            sign,
            fontName=FONT,
            fontSize=7,
            fillColor=colors.HexColor("#0B1D3A"),
            textAnchor="middle",
        ))

    for planet, position in chart["planets"].items():
        angle = pi / 2 - position["longitude"] * pi / 180
        x = center + (inner - 5 * mm) * cos(angle)
        y = center + (inner - 5 * mm) * sin(angle)
        drawing.add(Circle(x, y, 1.7 * mm, fillColor=colors.HexColor("#D4AF37"), strokeColor=None))
        drawing.add(String(
            center + (inner - 11 * mm) * cos(angle),
            center + (inner - 11 * mm) * sin(angle),
            planet[:2],
            fontName=FONT,
            fontSize=6,
            fillColor=colors.HexColor("#172033"),
            textAnchor="middle",
        ))
    drawing.add(String(center, center + 3 * mm, "Натальная", fontName=FONT, fontSize=12,
                       fillColor=colors.HexColor("#0B1D3A"), textAnchor="middle"))
    drawing.add(String(center, center - 3 * mm, "карта", fontName=FONT, fontSize=12,
                       fillColor=colors.HexColor("#0B1D3A"), textAnchor="middle"))
    return drawing


def _chart_summary(chart: dict) -> str:
    planets = chart["planets"]
    time_note = " (время приблизительное)" if chart.get("time_is_approximate") else ""
    return (
        f"Дата рождения: {chart['date']}\n"
        f"Местное время: {chart['time']}{time_note}\n"
        f"Часовой пояс: {chart['timezone']}\n"
        f"Расчётное UTC: {chart['utc_time']}\n"
        f"Солнце: {planets['Солнце']['sign']} · Луна: {planets['Луна']['sign']} · "
        f"Асцендент: {chart['ascendant']['sign']}"
    )


def generate_report(
    report_type: str,
    chart: dict,
    second_chart: dict | None,
    content: dict[str, Any],
    recipient_name: str | None = None,
    recipient_username: str | None = None,
    recipient_photo: Any | None = None,
) -> Path:
    if not content:
        raise ValueError("PDF нельзя сформировать без проверенного AI-анализа.")

    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    filename = output_dir / f"astro_{report_type}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    styles = getSampleStyleSheet()
    title = ParagraphStyle("AstroTitle", parent=styles["Title"], fontName=FONT, fontSize=24,
                           leading=30, alignment=TA_CENTER, textColor="#D4AF37")
    heading = ParagraphStyle("AstroHeading", parent=styles["Heading2"], fontName=FONT,
                             fontSize=16, leading=21, textColor="#0B1D3A", spaceBefore=10)
    body = ParagraphStyle("AstroBody", parent=styles["BodyText"], fontName=FONT,
                          fontSize=10.5, leading=16, textColor="#172033")
    caption = ParagraphStyle("AstroCaption", parent=body, fontSize=8.5, leading=11,
                             textColor="#52606D", alignment=TA_CENTER)

    story = [
        _paragraph("ASTRO MARY", title),
        Spacer(1, 8 * mm),
        _paragraph(content["title"], heading),
        Spacer(1, 4 * mm),
    ]
    if recipient_photo:
        story.extend([Image(recipient_photo, width=28 * mm, height=28 * mm), Spacer(1, 3 * mm)])
    if recipient_name:
        username = f" · @{recipient_username}" if recipient_username else ""
        story.extend([_paragraph(f"Для: {recipient_name}{username}", body), Spacer(1, 3 * mm)])
    story.extend([
        _paragraph(_chart_summary(chart), body),
        Spacer(1, 6 * mm),
        _natal_chart(chart),
        _paragraph("Диаграмма построена по рассчитанным положениям планет.", caption),
        PageBreak(),
        _paragraph("Исходные данные карты", heading),
        _planet_table(chart),
        Spacer(1, 5 * mm),
        _aspect_table(chart["aspects"]),
    ])
    if second_chart:
        story.extend([
            Spacer(1, 6 * mm),
            _paragraph("Карта партнёра", heading),
            _paragraph(_chart_summary(second_chart), body),
            Spacer(1, 3 * mm),
            _planet_table(second_chart),
        ])
        from services.astro import calculate_synastry
        story.extend([
            Spacer(1, 5 * mm),
            _aspect_table(calculate_synastry(chart, second_chart), "Синастрия"),
        ])
    story.extend([PageBreak(), _paragraph(content["intro"], body), Spacer(1, 4 * mm)])
    generated_by_title = {section["title"]: section for section in content["sections"]}
    for section, _ in SECTIONS[report_type]:
        section_content = generated_by_title[section]
        story.extend([
            _paragraph(section, heading),
            _paragraph(section_content["content"], body),
            Spacer(1, 2 * mm),
            _paragraph(f"Опора на расчёт: {'; '.join(section_content['references'])}", caption),
            Spacer(1, 4 * mm),
        ])
    story.extend([Spacer(1, 3 * mm), _paragraph(content["disclaimer"], caption)])
    doc = SimpleDocTemplate(
        str(filename),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(story)
    return filename
