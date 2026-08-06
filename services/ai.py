import json
import logging
from typing import Any

from services.astro import calculate_synastry
from config.settings import settings
from services.reports import SECTIONS

logger = logging.getLogger(__name__)
AI_TIMEOUT_SECONDS = 900.0

SYSTEM_PROMPT = """
Ты — автор персональных астрологических отчётов. Подготовь отчёт строго на русском языке.
Используй только факты из переданных расчётов: не придумывай положения планет, дома, аспекты
или события. Обращайся к читателю на «вы», пиши живо, бережно и без повторов.

Правила интерпретации:
— положения планет рассчитаны астрономически; их символические значения интерпретируй
бережно, без утверждений о судьбе;
— планета отвечает на вопрос «что проявляется»: Солнце — личность и воля, Луна — эмоции,
Меркурий — мышление и общение, Венера — отношения и ценности, Марс — энергия и действия;
— знак показывает, как проявляется планета; дом — в какой сфере жизни это заметнее;
— аспекты описывают связь тем: соединение усиливает их, тригон — более согласованное
взаимодействие, квадрат — внутреннее напряжение, оппозиция — необходимость баланса;
— для каждого раздела выбери только 2–4 наиболее значимых факта из allowed_facts, которые
соответствуют его теме. Не перечисляй все планеты, дома и аспекты подряд и не подставляй
случайные или слабые детали ради полноты;
— сначала объясняй важный паттерн карты, затем связывай его со сферой раздела и давай
мягкий практический ориентир. Не выдавай интерпретацию за факт;
— если time_is_approximate равно true, не делай уверенных выводов по домам и Асценденту:
объясни, что они ориентировочны, либо опирайся на планеты в знаках и аспекты.

Нельзя давать диагнозы, медицинские назначения, юридические или инвестиционные советы,
гарантировать доход, отношения или будущие события. Астрологические интерпретации подавай
как символический, развлекательный способ саморефлексии, а не как установленный факт.

Верни только JSON без Markdown:
{
  "title": "string",
  "intro": "string",
  "sections": [{
    "title": "string",
    "content": "string",
    "references": ["точные факты из allowed_facts"]
  }],
  "disclaimer": "string"
}
Список sections должен содержать каждый переданный раздел ровно один раз и в том же порядке.
Каждый раздел: 70–110 слов, минимум две конкретные ссылки из allowed_facts. Не повторяй
одни и те же формулировки и не используй данные, отсутствующие в allowed_facts.
""".strip()

SECTION_GUIDANCE = {
    "personality": {
        "Солнечный знак": "раскройте Солнце как основу воли, идентичности и способа проявляться",
        "Лунный знак": "раскройте Луну как эмоциональные потребности и привычный способ заботы о себе",
        "Асцендент": "опишите первое впечатление и внешний стиль только при точном времени рождения",
        "Личностные планеты": "свяжите Меркурий, Венеру и Марс с мышлением, близостью и действиями",
        "Социальные планеты": "опишите Юпитер и Сатурн через рост, ответственность и реализацию",
        "Высшие планеты": "покажите Уран, Нептун и Плутон как фон индивидуальности без фатализма",
        "Дома гороскопа": "выберите только дома с несколькими личными планетами или ключевыми связями",
        "Ключевые аспекты": "возьмите наиболее точные и тематически важные аспекты",
        "Карьера и призвание": "приоритет — Солнце, МС/10 дом и планеты в карьерных домах",
        "Кармические задачи": "говорите о направлениях осознанного роста, а не о долге или предопределении",
        "Любовь и отношения": "приоритет — Венера, Луна, Марс и 7 дом при точном времени",
        "Здоровье и энергия": "давайте только бережные общие рекомендации по ресурсу, без диагнозов",
        "Таланты и способности": "соберите повторяющиеся сильные мотивы карты в 2–3 способности",
    },
    "compatibility": {
        "Общий обзор": "сопоставьте Солнца и 1–2 важные синастрические связи",
        "Эмоциональная совместимость": "приоритет — Луна, её аспекты и взаимная поддержка",
        "Сексуальная совместимость": "приоритет — Венера, Марс и их аспекты без откровенных деталей",
        "Интеллектуальная совместимость": "приоритет — Меркурий и его связи с личными планетами",
        "Бытовая совместимость": "выведите практические договорённости из земных тем и аспектов Сатурна",
        "Кармические аспекты": "опишите важные повторяющиеся уроки как зоны осознанности, без фатализма",
        "Сильные стороны пары": "выберите 2–3 гармоничных или поддерживающих показателя",
        "Слабые стороны и риски": "выберите 1–2 напряжения и сразу дайте способ бережного диалога",
        "Совместимость по знакам": "сопоставьте стихии и качества Солнца, Луны или Венеры",
        "Рекомендации": "сформулируйте 3 реалистичных действия из уже названных сильных и слабых сторон",
    },
    "money": {
        "Финансовый профиль": "объясните способ обращаться с ресурсами через Венеру, Юпитер, Сатурн и дома",
        "Дом денег": "приоритет — 2 дом, его управитель и планеты в нём только при точном времени",
        "Дом работы и услуг": "приоритет — 6 дом и Меркурий как стиль ежедневной работы",
        "Дом инвестиций и партнёрских денег": "приоритет — 8 дом и аспекты к его показателям; без советов инвестировать",
        "Венера и Юпитер": "опишите ценности, возможности роста и стиль создания дохода без гарантий",
        "Сатурн и Плутон": "покажите дисциплину, границы и изменения отношения к деньгам без пугающих прогнозов",
        "Аспекты к денежным домам": "выберите самые точные связи с 2, 6 или 8 домом при точном времени",
        "Кармические установки": "переведите наблюдения в осознанные привычки, не утверждайте прошлые жизни",
        "Периоды возможностей": "не называйте даты и не обещайте доход; говорите о готовности к возможностям",
        "Лучшие профессии": "предложите направления, а не гарантированный выбор профессии",
        "Практические советы": "дайте конкретные безопасные привычки: бюджет, навыки, последовательность и границы",
    },
}
DEFAULT_SECTION_GUIDANCE = (
    "выберите 2–4 наиболее важных факта, прямо связанных с темой раздела, "
    "и объясните их как единый символический паттерн без перечисления всей карты"
)


def _chart_for_prompt(chart: dict) -> dict[str, Any]:
    return {
        "birth_date": chart["date"],
        "birth_time_local": chart["time"],
        "birth_time_utc": chart["utc_time"],
        "timezone": chart["timezone"],
        "time_is_approximate": chart["time_is_approximate"],
        "ascendant": chart["ascendant"],
        "houses": chart["houses"],
        "planets": chart["planets"],
        "aspects": chart["aspects"],
    }


def _allowed_facts(chart: dict, second_chart: dict | None) -> list[str]:
    facts = []
    for label, value in (("Карта 1", chart), ("Карта 2", second_chart)):
        if value is None:
            continue
        for planet, position in value["planets"].items():
            facts.append(
                f"{label}: {planet} в {position['sign']}, дом {position['house']}"
            )
        facts.append(f"{label}: Асцендент в {value['ascendant']['sign']}")
        for aspect in value["aspects"]:
            facts.append(
                f"{label}: {aspect['first']} {aspect['type']} {aspect['second']}"
            )
    if second_chart:
        for aspect in calculate_synastry(chart, second_chart):
            facts.append(
                f"Синастрия: {aspect['first']} {aspect['type']} {aspect['second']}"
            )
    # logger.info("Allowed facts: %s", facts)
    return facts


def build_prompt_payload(report_type: str, chart: dict, second_chart: dict | None) -> dict[str, Any]:
    if report_type not in SECTIONS:
        raise ValueError(f"Неизвестный тип отчёта: {report_type}")
    payload: dict[str, Any] = {
        "report_type": report_type,
        "language": "ru",
        "sections": [
            {
                "title": title,
                "brief": brief,
                "guidance": SECTION_GUIDANCE.get(report_type, {}).get(
                    title, DEFAULT_SECTION_GUIDANCE
                ),
            }
            for title, brief in SECTIONS[report_type]
        ],
        "primary_chart": _chart_for_prompt(chart),
        "partner_chart": _chart_for_prompt(second_chart) if second_chart else None,
        "synastry_aspects": calculate_synastry(chart, second_chart) if second_chart else [],
        "allowed_facts": _allowed_facts(chart, second_chart),
    }
    return payload


def _validate_content(
    content: Any,
    report_type: str,
    allowed_facts: set[str],
) -> dict[str, Any] | None:
    if not isinstance(content, dict) or not all(isinstance(content.get(key), str) for key in ("title", "intro", "disclaimer")):
        return None
    expected_titles = [title for title, _ in SECTIONS[report_type]]
    sections = content.get("sections")
    if not isinstance(sections, list) or len(sections) != len(expected_titles):
        return None
    if [section.get("title") for section in sections] != expected_titles:
        return None
    if not all(
        isinstance(section.get("content"), str)
        and 70 <= len(section["content"].split()) <= 110
        and isinstance(section.get("references"), list)
        and len(section["references"]) >= 2
        and all(reference in allowed_facts for reference in section["references"])
        for section in sections
    ):
        return None
    return content


async def generate_report_content(
    report_type: str, chart: dict, second_chart: dict | None = None
) -> dict[str, Any] | None:
    """Return validated AI content or None when a report cannot be generated."""
    if not settings.ai_api_key:
        return None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            timeout=AI_TIMEOUT_SECONDS,
        )
        response = await client.chat.completions.create(
            model=settings.ai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(build_prompt_payload(report_type, chart, second_chart), ensure_ascii=False),
                },
            ],
        )
        raw_content = response.choices[0].message.content
        if not raw_content:
            return None
        return _validate_content(
            json.loads(raw_content),
            report_type,
            set(_allowed_facts(chart, second_chart)),
        )
    except (ImportError, json.JSONDecodeError, TimeoutError, ValueError) as error:
        logger.warning("Не удалось получить AI-отчёт: %s", error)
        return None
    except Exception:
        logger.exception("Неожиданная ошибка генерации AI-отчёта")
        return None


async def get_aitunnel_balance() -> dict[str, float] | None:
    """Fetch the current AITUNNEL account balance without exposing the API key."""
    if not settings.ai_api_key:
        return None
    try:
        import httpx

        balance_url = f"{settings.ai_base_url.rstrip('/')}/aitunnel/balance"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                balance_url,
                headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            )
            response.raise_for_status()
        data = response.json()
        balance = data.get("balance")
        if not isinstance(balance, (int, float)):
            return None
        return {"balance": float(balance)}
    except Exception:
        logger.exception("Не удалось получить баланс AITUNNEL")
        return None
