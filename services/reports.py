from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Flowable

NAVY = colors.HexColor("#17130F")
GOLD = colors.HexColor("#17130F")
GOLD_LIGHT = colors.HexColor("#8E8478")
PAPER = colors.HexColor("#F3E9D8")
INK = colors.HexColor("#17130F")
MUTED = colors.HexColor("#3D3731")

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
SYMBOL_FONT = "Helvetica"
for regular_path, bold_path in (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
):
    if Path(regular_path).exists() and Path(bold_path).exists():
        pdfmetrics.registerFont(TTFont("AstroFont", regular_path))
        pdfmetrics.registerFont(TTFont("AstroFont-Bold", bold_path))
        FONT = "AstroFont"
        FONT_BOLD = "AstroFont-Bold"
        break

symbol_font_path = Path("C:/Windows/Fonts/seguisym.ttf")
if symbol_font_path.exists():
    pdfmetrics.registerFont(TTFont("AstroSymbols", str(symbol_font_path)))
    SYMBOL_FONT = "AstroSymbols"
else:
    # DejaVu Sans is available in the container and contains the astronomical
    # and zodiac glyphs used by the report.
    SYMBOL_FONT = FONT

SECTIONS = {
    "personality": [
        ("Введение", "как устроена натальная карта и как читать этот отчёт"),
        ("Солнечный знак", "характер, сильные и слабые стороны"),
        ("Лунный знак", "эмоции, интуиция и потребность в заботе"),
        ("Асцендент", "внешний образ и первое впечатление"),
        ("Личностные планеты", "общение, любовь и энергия"),
        ("Социальные планеты", "карьерные возможности, успех и ответственность"),
        ("Высшие планеты", "уникальные таланты, творческий потенциал и трансформации"),
        ("Дома гороскопа", "главные сферы жизни и акцентные дома"),
        ("Ключевые аспекты", "сильные стороны и основные вызовы карты"),
        ("Кармические задачи", "направления роста и внутренние уроки"),
        ("Любовь и отношения", "подход к любви и подходящие партнёры"),
        ("Карьера и призвание", "конкретные роли, сферы деятельности и рабочие задачи"),
        ("Здоровье и энергия", "бережная поддержка ресурса и восстановления"),
        ("Таланты и способности", "врождённые дары и навыки, которые стоит развивать"),
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
        ("Лучшие профессии", "конкретные роли, сферы деятельности и профессиональные задачи"),
        ("Практические советы", "реалистичные действия для работы с привычками"),
        ("Заключение", "главное направление для развития финансовой устойчивости"),
    ],
}

ZODIAC_SHORT = ("Ове", "Тел", "Бли", "Рак", "Лев", "Дев", "Вес", "Ско", "Стр", "Коз", "Вод", "Рыб")
ZODIAC_NAMES = (
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы",
)
ZODIAC_SYMBOLS = ("♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓")
MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
PLANET_SYMBOLS = {
    "Солнце": "☉",
    "Луна": "☾",
    "Меркурий": "☿",
    "Венера": "♀",
    "Марс": "♂",
    "Юпитер": "♃",
    "Сатурн": "♄",
    "Земля": "🜨",
    "Уран": "⛢",
    "Нептун": "♆",
    "Плутон": "♇",
}


def _planet_label(planet: str) -> str:
    return f"{PLANET_SYMBOLS.get(planet, '')} {planet}".strip()


def _planet_paragraph(planet: str, color=INK) -> Paragraph:
    symbol = escape(PLANET_SYMBOLS.get(planet, ""))
    name = escape(planet)
    markup = f'<font name="{SYMBOL_FONT}">{symbol}</font> {name}'
    style = ParagraphStyle(
        "AstroTableSymbol",
        fontName=FONT,
        fontSize=14,
        leading=18,
        textColor=color,
    )
    return Paragraph(markup, style)


def _zodiac_paragraph(index: int, name: str, color=INK) -> Paragraph:
    markup = (
        f'<font name="{SYMBOL_FONT}">{ZODIAC_SYMBOLS[index]}</font> '
        f"{escape(name)}"
    )
    style = ParagraphStyle(
        "AstroZodiacSymbol",
        fontName=FONT,
        fontSize=14,
        leading=18,
        textColor=color,
    )
    return Paragraph(markup, style)


def _zodiac_image_path(index: int) -> Path:
    return Path(__file__).resolve().parent.parent / "imgs" / "zodiac" / f"{ZODIAC_NAMES[index]}_15.png"


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _format_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return value
    return f"{parsed.day} {MONTHS_GENITIVE[parsed.month - 1]} {parsed.year}"


def _format_utc(value: str) -> str:
    try:
        parsed = datetime.strptime(value.removesuffix(" UTC"), "%Y-%m-%d %H:%M")
    except (AttributeError, ValueError):
        return value
    month = MONTHS_GENITIVE[parsed.month - 1]
    return f"{parsed.day} {month} {parsed.year}, {parsed:%H:%M} UTC"


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 14),
        ("LEADING", (0, 0), (-1, -1), 18),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _planet_table(chart: dict) -> Table:
    rows = [["Планета", "Знак", "Градус", "Дом"]]
    for planet, position in chart["planets"].items():
        rows.append([
            _planet_paragraph(planet),
            _zodiac_paragraph(
                int(position["longitude"] // 30) % 12,
                position["sign"],
            ),
            f"{position['degree']:.1f}°",
            str(position["house"]),
        ])
    return _table(rows, [43 * mm, 42 * mm, 32 * mm, 25 * mm])


def _aspect_table(aspects: list[dict], title: str = "Аспекты") -> Table:
    rows = [[title, "Тип", "Орбис"]]
    for aspect in aspects[:20]:
        rows.append([
            Paragraph(
                f'<font name="{SYMBOL_FONT}">{escape(PLANET_SYMBOLS.get(aspect["first"], ""))}</font> '
                f'{escape(aspect["first"])} — '
                f'<font name="{SYMBOL_FONT}">{escape(PLANET_SYMBOLS.get(aspect["second"], ""))}</font> '
                f'{escape(aspect["second"])}',
                ParagraphStyle(
                    "AstroAspectSymbol",
                    fontName=FONT,
                    fontSize=14,
                    leading=18,
                    textColor=INK,
                ),
            ),
            aspect["type"],
            f"{aspect['orb']:.1f}°",
        ])
    if len(rows) == 1:
        rows.append(["Нет мажорных аспектов", "—", "—"])
    return _table(rows, [80 * mm, 42 * mm, 20 * mm])


def _house_table(chart: dict) -> Table:
    rows = [["Дом", "Куспид", "Знак"]]
    for index, longitude in enumerate(chart["houses"], start=1):
        rows.append([
            str(index),
            f"{longitude % 30:.1f}°",
            _zodiac_paragraph(
                int(longitude // 30) % 12,
                ZODIAC_NAMES[int(longitude // 30) % 12],
            ),
        ])
    return _table(rows, [35 * mm, 45 * mm, 62 * mm])


def _synastry_aspects(first_chart: dict, second_chart: dict) -> list[dict]:
    aspects = []
    for first_name, first in first_chart["planets"].items():
        for second_name, second in second_chart["planets"].items():
            distance = abs(first["longitude"] - second["longitude"])
            distance = min(distance, 360 - distance)
            for angle, aspect_type, orb in (
                (0, "соединение", 8),
                (60, "секстиль", 5),
                (90, "квадрат", 6),
                (120, "тригон", 6),
                (180, "оппозиция", 8),
            ):
                difference = abs(distance - angle)
                if difference <= orb:
                    aspects.append({
                        "first": first_name,
                        "second": second_name,
                        "type": aspect_type,
                        "angle": angle,
                        "orb": round(difference, 2),
                    })
                    break
    return aspects


class NatalChartFlowable(Flowable):
    """Renders the natal wheel on canvas so PNG transparency works via mask='auto'."""

    def __init__(self, chart: dict, size: float = 150 * mm):
        super().__init__()
        self.chart = chart
        self.size = size
        self.width = size
        self.height = size
        self.hAlign = "CENTER"

    def draw(self) -> None:
        from math import cos, pi, sin

        canvas = self.canv
        size = self.size
        center = size / 2
        outer = 60 * mm
        inner = 43 * mm
        icon_size = 16 * mm
        zodiac_icon_radius = outer - 8.5 * mm

        canvas.saveState()
        canvas.setFillColor(PAPER)
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(1.8)
        canvas.circle(center, center, outer, fill=1, stroke=1)

        canvas.setStrokeColor(INK)
        canvas.setLineWidth(1.1)
        canvas.circle(center, center, inner, fill=0, stroke=1)

        canvas.setStrokeColor(GOLD_LIGHT)
        canvas.setLineWidth(0.8)
        for index, symbol in enumerate(ZODIAC_SYMBOLS):
            angle = pi / 2 - index * pi / 6
            canvas.line(
                center + inner * cos(angle),
                center + inner * sin(angle),
                center + outer * cos(angle),
                center + outer * sin(angle),
            )
            text_angle = angle - pi / 12
            icon_center_x = center + zodiac_icon_radius * cos(text_angle)
            icon_center_y = center + zodiac_icon_radius * sin(text_angle)
            icon_path = _zodiac_image_path(index)
            if icon_path.exists():
                canvas.drawImage(
                    str(icon_path),
                    icon_center_x - icon_size / 2,
                    icon_center_y - icon_size / 2,
                    width=icon_size,
                    height=icon_size,
                    mask="auto",
                )
            else:
                canvas.setFillColor(NAVY)
                canvas.setFont(SYMBOL_FONT, 11)
                canvas.drawCentredString(icon_center_x, icon_center_y - 3, symbol)

        for planet, position in self.chart["planets"].items():
            angle = pi / 2 - position["longitude"] * pi / 180
            planet_x = center + (inner - 5 * mm) * cos(angle)
            planet_y = center + (inner - 5 * mm) * sin(angle)
            canvas.setFillColor(INK)
            canvas.setStrokeColor(INK)
            canvas.setLineWidth(0.4)
            canvas.circle(planet_x, planet_y, 1.7 * mm, fill=1, stroke=1)
            canvas.setFillColor(INK)
            canvas.setFont(SYMBOL_FONT, 16.5)
            canvas.drawCentredString(
                center + (inner - 11 * mm) * cos(angle),
                center + (inner - 11 * mm) * sin(angle) - 3,
                PLANET_SYMBOLS.get(planet, planet[:2]),
            )

        canvas.setFillColor(NAVY)
        canvas.setFont(FONT, 16)
        canvas.drawCentredString(center, center + 3 * mm, "Натальная")
        canvas.drawCentredString(center, center - 3 * mm, "карта")
        canvas.restoreState()


def _natal_chart(chart: dict) -> NatalChartFlowable:
    return NatalChartFlowable(chart)


def _draw_page_frame(canvas: Canvas, doc) -> None:
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)

    canvas.setFont(FONT, 9.5)
    canvas.setFillColor(INK)
    canvas.drawString(23 * mm, 10 * mm, "ASTRO MARY")
    canvas.drawRightString(width - 23 * mm, 10 * mm, f"{doc.page}")
    canvas.restoreState()


def _chart_summary(chart: dict) -> str:
    planets = chart["planets"]
    time_note = " (время приблизительное)" if chart.get("time_is_approximate") else ""
    return (
        f"Дата рождения: {_format_date(chart['date'])}\n"
        f"Местное время: {chart['time']}{time_note}\n"
        f"Часовой пояс: {chart['timezone']}\n"
        f"Расчётное UTC: {_format_utc(chart['utc_time'])}\n"
        f"Солнце: {PLANET_SYMBOLS['Солнце']} {planets['Солнце']['sign']} · "
        f"Луна: {PLANET_SYMBOLS['Луна']} {planets['Луна']['sign']} · "
        f"Асцендент: {ZODIAC_SYMBOLS[int(chart['ascendant']['longitude'] // 30) % 12]} "
        f"{chart['ascendant']['sign']}"
    )


def _chart_summary_table(
    chart: dict,
    label_style: ParagraphStyle,
    value_style: ParagraphStyle,
) -> Table:
    planets = chart["planets"]
    ascendant_index = int(chart["ascendant"]["longitude"] // 30) % 12
    symbol_span = f'<font name="{SYMBOL_FONT}">'
    rows = [
        [_paragraph("Дата рождения:", label_style),
         _paragraph(_format_date(chart["date"]), value_style)],
        [_paragraph("Часовой пояс:", label_style),
         _paragraph(chart["timezone"], value_style)],
        [
            _paragraph("Положение Солнца:", label_style),
            Paragraph(
                f"{symbol_span}{PLANET_SYMBOLS['Солнце']}</font> "
                f"{escape(planets['Солнце']['sign'])}",
                value_style,
            ),
        ],
        [
            _paragraph("Положение Луны:", label_style),
            Paragraph(
                f"{symbol_span}{PLANET_SYMBOLS['Луна']}</font> "
                f"{escape(planets['Луна']['sign'])}",
                value_style,
            ),
        ],
        [
            _paragraph("Асцендент:", label_style),
            Paragraph(
                f"{symbol_span}{ZODIAC_SYMBOLS[ascendant_index]}</font> "
                f"{escape(chart['ascendant']['sign'])}",
                value_style,
            ),
        ],
    ]
    if not chart.get("time_is_approximate"):
        rows.insert(1, [
            _paragraph("Местное время:", label_style),
            _paragraph(chart["time"], value_style),
        ])
    table = Table(rows, colWidths=[70 * mm, 65 * mm], hAlign="CENTER")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    return table


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
    title = ParagraphStyle("AstroTitle", parent=styles["Title"], fontName=FONT_BOLD, fontSize=35,
                           leading=43, alignment=TA_CENTER, textColor=NAVY, spaceAfter=5 * mm)
    eyebrow = ParagraphStyle("AstroEyebrow", parent=styles["BodyText"], fontName=FONT,
                             fontSize=12, leading=16, alignment=TA_CENTER, textColor=GOLD,
                             spaceAfter=4 * mm)
    heading = ParagraphStyle("AstroHeading", parent=styles["Heading2"], fontName=FONT_BOLD,
                             fontSize=23, leading=30, textColor=NAVY,
                             spaceBefore=7 * mm, spaceAfter=3 * mm)
    body = ParagraphStyle("AstroBody", parent=styles["BodyText"], fontName=FONT,
                          fontSize=15, leading=24, textColor=INK,
                          alignment=4, firstLineIndent=8 * mm, spaceAfter=4 * mm)
    caption = ParagraphStyle("AstroCaption", parent=body, fontSize=13, leading=18,
                             textColor=MUTED, alignment=TA_CENTER, firstLineIndent=0)
    summary_label = ParagraphStyle(
        "AstroSummaryLabel",
        parent=body,
        fontName=FONT_BOLD,
        fontSize=15,
        leading=21,
        alignment=0,
        textColor=INK,
        firstLineIndent=0,
        spaceAfter=0,
    )
    summary_value = ParagraphStyle(
        "AstroSummaryValue",
        parent=body,
        fontName=FONT_BOLD,
        fontSize=17,
        leading=23,
        alignment=2,
        textColor=INK,
        firstLineIndent=0,
        spaceAfter=0,
    )
    recipient_style = ParagraphStyle("AstroRecipient", parent=heading, fontSize=22,
                                     leading=28, alignment=TA_CENTER, spaceBefore=2 * mm)
    type_titles = {
        "personality": "РАЗБОР ЛИЧНОСТИ",
        "compatibility": "СОВМЕСТИМОСТЬ",
        "money": "ДЕНЕЖНЫЙ КОД",
    }

    story = [
        Spacer(1, 18 * mm),
        _paragraph("ASTRO MARY · ПЕРСОНАЛЬНЫЙ ОТЧЁТ", eyebrow),
        _paragraph(type_titles[report_type], title),
        Spacer(1, 15 * mm),
    ]
    if recipient_photo:
        photo = Image(recipient_photo, width=30 * mm, height=30 * mm)
        photo.hAlign = "CENTER"
        story.extend([photo, Spacer(1, 4 * mm)])
    if recipient_name:
        username = f" · @{recipient_username}" if recipient_username else ""
        story.extend([
            _paragraph(f"{recipient_name}{username}", recipient_style),
            Spacer(1, 2 * mm),
        ])
    story.extend([
        _chart_summary_table(chart, summary_label, summary_value),
        PageBreak(),
        _paragraph("ВАША КАРТА", eyebrow),
        _paragraph("Натальная диаграмма", heading),
        Spacer(1, 4 * mm),
        _natal_chart(chart),
        _paragraph("Карта построена по рассчитанным положениям планет", caption),
        PageBreak(),
        _paragraph("ОСНОВА ИНТЕРПРЕТАЦИИ", eyebrow),
        _paragraph("Исходные данные карты", heading),
        KeepTogether([_planet_table(chart)]),
        Spacer(1, 5 * mm),
        KeepTogether([_aspect_table(chart["aspects"])]),
        Spacer(1, 5 * mm),
        KeepTogether([
            _paragraph("Куспиды домов", heading),
            _house_table(chart),
        ]),
    ])
    if second_chart:
        story.extend([
            PageBreak(),
            _paragraph("ВТОРАЯ КАРТА", eyebrow),
            _paragraph("Карта партнёра", heading),
            _chart_summary_table(second_chart, summary_label, summary_value),
            Spacer(1, 4 * mm),
            _natal_chart(second_chart),
            Spacer(1, 4 * mm),
            KeepTogether([_planet_table(second_chart)]),
        ])
        story.extend([
            Spacer(1, 5 * mm),
            KeepTogether([
                _aspect_table(_synastry_aspects(chart, second_chart), "Синастрия"),
            ]),
        ])
    story.extend([
        PageBreak(),
        _paragraph("ПЕРСОНАЛЬНАЯ ИНТЕРПРЕТАЦИЯ", eyebrow),
        _paragraph(content["title"], title),
        Spacer(1, 5 * mm),
        _paragraph(content["intro"], body),
        Spacer(1, 5 * mm),
    ])
    generated_by_title = {section["title"]: section for section in content["sections"]}
    for section_number, (section, _) in enumerate(SECTIONS[report_type], start=1):
        section_content = generated_by_title[section]
        story.extend([
            KeepTogether([
                _paragraph(f"РАЗДЕЛ {section_number:02d}", eyebrow),
                _paragraph(section, heading),
            ]),
            _paragraph(section_content["content"], body),
            Table(
                [[_paragraph(
                    f"Опора на расчёт: {'; '.join(section_content['references'])}",
                    caption,
                )]],
                colWidths=[142 * mm],
                style=TableStyle([
                    ("LINEABOVE", (0, 0), (-1, 0), 0.5, GOLD),
                    ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ]),
            ),
            Spacer(1, 8 * mm),
        ])
    story.extend([
        PageBreak(),
        Spacer(1, 60 * mm),
        _paragraph("ЗАКЛЮЧЕНИЕ", eyebrow),
        _paragraph("Спасибо за доверие", title),
        Spacer(1, 8 * mm),
        _paragraph(content["disclaimer"], caption),
    ])
    doc = SimpleDocTemplate(
        str(filename),
        pagesize=A4,
        rightMargin=25 * mm,
        leftMargin=25 * mm,
        topMargin=23 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(story, onFirstPage=_draw_page_frame, onLaterPages=_draw_page_frame)
    return filename
