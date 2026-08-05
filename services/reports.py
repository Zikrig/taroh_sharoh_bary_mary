from pathlib import Path
from datetime import datetime
from typing import Any

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

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
        ("Ключевые аспекты", "суперсилы и основные вызовы карты"),
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


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text.replace("&", "&amp;").replace("\n", "<br/>"), style)


def generate_report(
    report_type: str,
    chart: dict,
    second_chart: dict | None = None,
    content: dict[str, Any] | None = None,
) -> Path:
    output_dir = Path("reports")
    output_dir.mkdir(exist_ok=True)
    filename = output_dir / f"astro_{report_type}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    styles = getSampleStyleSheet()
    title = ParagraphStyle("AstroTitle", parent=styles["Title"], fontName=FONT,
                           fontSize=24, leading=30, alignment=TA_CENTER, textColor="#D4AF37")
    heading = ParagraphStyle("AstroHeading", parent=styles["Heading2"], fontName=FONT,
                             fontSize=16, leading=21, textColor="#0B1D3A", spaceBefore=10)
    body = ParagraphStyle("AstroBody", parent=styles["BodyText"], fontName=FONT,
                          fontSize=10.5, leading=16, textColor="#172033")
    report_title = content.get("title", "Персональный отчёт по вашей карте") if content else "Персональный отчёт по вашей карте"
    story = [_paragraph("ASTRO MARY", title), Spacer(1, 10 * mm),
             _paragraph(report_title, body), Spacer(1, 8 * mm)]
    planets = chart["planets"]
    summary = (
        f"Дата: {chart['date']}<br/>Время: {chart['time']}<br/>"
        f"Солнце: {planets['Солнце']['sign']} · Луна: {planets['Луна']['sign']} · "
        f"Асцендент: {chart['ascendant']['sign']}"
    )
    story.append(_paragraph(summary, body))
    story.append(PageBreak())
    generated_sections = content.get("sections", []) if content else []
    generated_by_title = {section["title"]: section["content"] for section in generated_sections}
    if content and content.get("intro"):
        story.append(_paragraph(content["intro"], body))
        story.append(Spacer(1, 4 * mm))
    for section, subject in SECTIONS[report_type]:
        story.append(_paragraph(section, heading))
        fallback_text = (
            f"{subject.capitalize()}. В вашей карте особенно заметна энергия знака "
            f"{planets['Солнце']['sign']}. Используйте сильные стороны этого положения "
            "осознанно: наблюдайте за реакциями, проверяйте решения практикой и оставляйте "
            "пространство для гибкости. Этот раздел подготовлен как бережная навигация, "
            "а не как медицинская или финансовая рекомендация."
        )
        story.append(_paragraph(generated_by_title.get(section, fallback_text), body))
        story.append(Spacer(1, 4 * mm))
    disclaimer = content.get("disclaimer") if content else None
    if disclaimer:
        story.append(_paragraph(disclaimer, body))
    doc = SimpleDocTemplate(str(filename), pagesize=A4, rightMargin=18 * mm,
                            leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    doc.build(story)
    return filename
