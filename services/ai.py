import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.astro import calculate_synastry
from config.settings import settings
from services.prompt_guides.career import build_career_hints
from services.reports import SECTIONS

logger = logging.getLogger(__name__)
AI_TIMEOUT_SECONDS = 240.0
SECTIONS_PER_REQUEST = 3
MAX_PARALLEL_REQUESTS = 3
FAILED_BATCH_RETRIES = 1
PAYLOAD_SAMPLES_DIR = Path("data/payload_samples")

PERSONAL_PLANETS = frozenset({"Солнце", "Луна", "Меркурий", "Венера", "Марс"})
SOCIAL_PLANETS = frozenset({"Юпитер", "Сатурн"})
OUTER_PLANETS = frozenset({"Уран", "Нептун", "Плутон"})
ALL_PLANETS = PERSONAL_PLANETS | SOCIAL_PLANETS | OUTER_PLANETS
HARD_ASPECTS = frozenset({"квадрат", "оппозиция"})

# Per-section focus: which facts/chart pieces a batch actually needs.
# "aspects": "involving" | "all" | "hard" | "none"
SECTION_CONTEXT_FOCUS: dict[str, dict[str, Any]] = {
    "Введение": {
        "planets": frozenset({"Солнце", "Луна"}),
        "ascendant": True,
        "aspects": "involving",
    },
    "Солнечный знак": {
        "planets": frozenset({"Солнце"}),
        "aspects": "involving",
    },
    "Лунный знак": {
        "planets": frozenset({"Луна"}),
        "aspects": "involving",
    },
    "Асцендент": {
        "planets": frozenset({"Солнце"}),
        "ascendant": True,
        "aspects": "involving",
    },
    "Личностные планеты": {
        "planets": PERSONAL_PLANETS,
        "aspects": "involving",
    },
    "Социальные планеты": {
        "planets": SOCIAL_PLANETS | frozenset({"Солнце", "Уран"}),
        "aspects": "involving",
        "career": True,
    },
    "Высшие планеты": {
        "planets": OUTER_PLANETS,
        "aspects": "involving",
        "career": True,
    },
    "Дома гороскопа": {
        "planets": ALL_PLANETS,
        "ascendant": True,
        "aspects": "none",
        "keep_houses": True,
        "career": True,
    },
    "Ключевые аспекты": {
        "planets": ALL_PLANETS,
        "aspects": "all",
    },
    "Кармические задачи": {
        "planets": ALL_PLANETS,
        "aspects": "hard",
    },
    "Любовь и отношения": {
        "planets": frozenset({"Венера", "Луна", "Марс"}),
        "houses": frozenset({7}),
        "aspects": "involving",
    },
    "Карьера и призвание": {
        "planets": ALL_PLANETS,
        "houses": frozenset({2, 6, 10}),
        "aspects": "involving",
        "career": True,
    },
    "Здоровье и энергия": {
        "planets": frozenset({"Солнце", "Луна", "Марс"}),
        "aspects": "involving",
    },
    "Таланты и способности": {
        "planets": ALL_PLANETS,
        "aspects": "involving",
        "career": True,
    },
    "Заключение": {
        "planets": frozenset({"Солнце", "Луна", "Сатурн"}),
        "ascendant": True,
        "aspects": "involving",
    },
    "Общий обзор": {
        "planets": frozenset({"Солнце", "Луна"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Эмоциональная совместимость": {
        "planets": frozenset({"Луна"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Сексуальная совместимость": {
        "planets": frozenset({"Венера", "Марс"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Интеллектуальная совместимость": {
        "planets": frozenset({"Меркурий"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Бытовая совместимость": {
        "planets": frozenset({"Сатурн", "Луна", "Венера"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Кармические аспекты": {
        "planets": ALL_PLANETS,
        "aspects": "hard",
        "synastry": True,
    },
    "Сильные стороны пары": {
        "planets": ALL_PLANETS,
        "aspects": "involving",
        "synastry": True,
    },
    "Слабые стороны и риски": {
        "planets": ALL_PLANETS,
        "aspects": "hard",
        "synastry": True,
    },
    "Совместимость по знакам": {
        "planets": frozenset({"Солнце", "Луна", "Венера"}),
        "aspects": "none",
        "synastry": True,
    },
    "Рекомендации": {
        "planets": frozenset({"Солнце", "Луна", "Венера", "Марс", "Меркурий"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Финансовый профиль": {
        "planets": frozenset({"Венера", "Юпитер", "Сатурн", "Солнце"}),
        "houses": frozenset({2, 8, 10}),
        "aspects": "involving",
        "career": True,
    },
    "Дом денег": {
        "planets": ALL_PLANETS,
        "houses": frozenset({2}),
        "aspects": "involving",
        "career": True,
    },
    "Дом работы и услуг": {
        "planets": ALL_PLANETS | frozenset({"Меркурий"}),
        "houses": frozenset({6}),
        "aspects": "involving",
        "career": True,
    },
    "Дом инвестиций и партнёрских денег": {
        "planets": ALL_PLANETS,
        "houses": frozenset({8}),
        "aspects": "involving",
    },
    "Венера и Юпитер": {
        "planets": frozenset({"Венера", "Юпитер"}),
        "aspects": "involving",
        "career": True,
    },
    "Сатурн и Плутон": {
        "planets": frozenset({"Сатурн", "Плутон"}),
        "aspects": "involving",
    },
    "Аспекты к денежным домам": {
        "planets": ALL_PLANETS,
        "houses": frozenset({2, 6, 8}),
        "aspects": "all",
    },
    "Кармические установки": {
        "planets": frozenset({"Сатурн", "Плутон", "Луна", "Венера"}),
        "aspects": "hard",
    },
    "Периоды возможностей": {
        "planets": frozenset({"Юпитер", "Сатурн", "Солнце"}),
        "aspects": "involving",
    },
    "Лучшие профессии": {
        "planets": ALL_PLANETS,
        "houses": frozenset({2, 6, 10}),
        "aspects": "involving",
        "career": True,
    },
    "Практические советы": {
        "planets": frozenset({"Венера", "Сатурн", "Меркурий"}),
        "aspects": "involving",
        "career": True,
    },
}
DEFAULT_SECTION_FOCUS = {
    "planets": frozenset({"Солнце", "Луна"}),
    "ascendant": True,
    "aspects": "involving",
}

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
— в разделах о карьере, профессиях, доходе, талантах и способностях называй 2–4 конкретных
варианта: роль, сферу, тип задач или рабочую среду. Для каждого варианта коротко объясняй,
какие факты карты на него указывают. Примеры конкретики: UX-исследователь, аналитик данных,
редактор образовательных продуктов, менеджер партнёрств — а не «творческая работа»;
— называй варианты развития и навыки, а не единственную «предназначенную» профессию, гарантии
успеха, уровень дохода или сроки результата.

Нельзя давать диагнозы, медицинские назначения, юридические или инвестиционные советы,
гарантировать доход, отношения или будущие события. Астрологические интерпретации подавай
как символический, развлекательный способ саморефлексии, а не как установленный факт.

Верни только JSON без Markdown в формате:
{
  "sections": [{
    "title": "string",
    "content": "string",
    "references": ["точные факты из allowed_facts"]
  }]
}
Верни только запрошенные в этом пакете sections, ровно по одному разу и в том же порядке.
Для каждого раздела напиши содержательный текст и укажи 1–3 точные строки из allowed_facts,
на которых основана интерпретация. Объём каждого раздела — от 30 до 140 слов.
Не используй данные, отсутствующие в allowed_facts.
""".strip()

SECTION_GUIDANCE = {
    "personality": {
        "Асцендент": "опишите первое впечатление и внешний стиль только при точном времени рождения",
        "Личностные планеты": "свяжите мышление, близость и действия с конкретными сильными навыками",
        "Социальные планеты": "опишите стиль роста, ответственности и профессиональной реализации",
        "Высшие планеты": "выделите необычный способ создавать новое, видеть системы или работать с образами",
        "Дома гороскопа": "используйте темы акцентных домов и профессии-подсказки только при точном времени рождения",
        "Ключевые аспекты": "возьмите наиболее точные и тематически важные аспекты",
        "Кармические задачи": "говорите о направлениях осознанного роста, а не о долге или предопределении",
        "Любовь и отношения": "приоритет — Венера, Луна, Марс и 7 дом при точном времени",
        "Карьера и призвание": "предложите 2–4 конкретные роли или сферы, тип задач и рабочую среду; каждую рекомендацию свяжите с фактами карты",
        "Здоровье и энергия": "давайте только бережные общие рекомендации по ресурсу, без диагнозов",
        "Таланты и способности": "назовите 2–4 наблюдаемых навыка или формата деятельности и объясните их связью нескольких показателей",
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
        "Лучшие профессии": "предложите 2–4 конкретные роли или сферы, тип задач и рабочую среду без гарантии дохода",
        "Практические советы": "дайте конкретные безопасные привычки: бюджет, навыки, последовательность и границы; не советуйте инвестиции, талисманы или аффирмации как способ заработка",
    },
}
DEFAULT_SECTION_GUIDANCE = (
    "выберите 2–4 наиболее важных факта, прямо связанных с темой раздела, "
    "и объясните их как единый символический паттерн без перечисления всей карты"
)


def _save_payload_sample(
    kind: str,
    payload: Any,
    *,
    report_type: str,
    attempt: int,
    request_id: str,
) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{kind}_{timestamp}_{request_id}_{report_type}_attempt{attempt}.json"
    try:
        PAYLOAD_SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
        (PAYLOAD_SAMPLES_DIR / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as error:
        logger.warning("Не удалось сохранить AI %s в payload_samples: %s", kind, error)


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


def _facts_from_prompt_charts(
    primary_chart: dict[str, Any] | None,
    partner_chart: dict[str, Any] | None,
    synastry_aspects: list[dict[str, Any]] | None,
    *,
    include_ascendant: bool = True,
) -> list[str]:
    """Render citation strings from structured chart JSON for the prompt."""
    facts: list[str] = []
    for label, chart in (("Карта 1", primary_chart), ("Карта 2", partner_chart)):
        if chart is None:
            continue
        for planet, position in (chart.get("planets") or {}).items():
            facts.append(
                f"{label}: {planet} в {position['sign']}, дом {position['house']}"
            )
        if include_ascendant and chart.get("ascendant"):
            facts.append(f"{label}: Асцендент в {chart['ascendant']['sign']}")
        for aspect in chart.get("aspects") or []:
            facts.append(
                f"{label}: {aspect['first']} {aspect['type']} {aspect['second']}"
            )
    for aspect in synastry_aspects or []:
        facts.append(
            f"Синастрия: {aspect['first']} {aspect['type']} {aspect['second']}"
        )
    return facts


def _allowed_facts(chart: dict, second_chart: dict | None) -> list[str]:
    return _facts_from_prompt_charts(
        _chart_for_prompt(chart),
        _chart_for_prompt(second_chart) if second_chart else None,
        calculate_synastry(chart, second_chart) if second_chart else [],
        include_ascendant=True,
    )


def build_prompt_payload(report_type: str, chart: dict, second_chart: dict | None) -> dict[str, Any]:
    if report_type not in SECTIONS:
        raise ValueError(f"Неизвестный тип отчёта: {report_type}")
    primary_chart = _chart_for_prompt(chart)
    partner_chart = _chart_for_prompt(second_chart) if second_chart else None
    synastry_aspects = calculate_synastry(chart, second_chart) if second_chart else []
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
        "primary_chart": primary_chart,
        "partner_chart": partner_chart,
        "synastry_aspects": synastry_aspects,
        "allowed_facts": _facts_from_prompt_charts(
            primary_chart,
            partner_chart,
            synastry_aspects,
        ),
        "career_and_talent_hints": build_career_hints(
            chart,
            include_houses=not chart["time_is_approximate"],
        ),
    }
    return payload


def _section_batches(sections: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    return [
        sections[index:index + SECTIONS_PER_REQUEST]
        for index in range(0, len(sections), SECTIONS_PER_REQUEST)
    ]


def _merge_focus(titles: list[str]) -> dict[str, Any]:
    planets: set[str] = set()
    houses: set[int] = set()
    aspect_modes: set[str] = set()
    ascendant = False
    career = False
    synastry = False
    keep_houses = False
    for title in titles:
        focus = SECTION_CONTEXT_FOCUS.get(title, DEFAULT_SECTION_FOCUS)
        planets.update(focus.get("planets") or ())
        houses.update(focus.get("houses") or ())
        aspect_modes.add(focus.get("aspects") or "involving")
        ascendant = ascendant or bool(focus.get("ascendant"))
        career = career or bool(focus.get("career"))
        synastry = synastry or bool(focus.get("synastry"))
        keep_houses = (
            keep_houses
            or bool(focus.get("keep_houses"))
            or bool(focus.get("houses"))
            or bool(focus.get("career"))
        )
    if "all" in aspect_modes:
        aspect_mode = "all"
    elif "hard" in aspect_modes and "involving" not in aspect_modes:
        aspect_mode = "hard"
    elif "none" in aspect_modes and len(aspect_modes) == 1:
        aspect_mode = "none"
    else:
        aspect_mode = "involving"
    return {
        "planets": frozenset(planets) or frozenset({"Солнце", "Луна"}),
        "houses": frozenset(houses),
        "aspects": aspect_mode,
        "ascendant": ascendant,
        "career": career,
        "synastry": synastry,
        "keep_houses": keep_houses,
    }


def _filter_aspects(
    aspects: list[dict[str, Any]],
    focus: dict[str, Any],
) -> list[dict[str, Any]]:
    mode = focus["aspects"]
    planets = focus["planets"]
    if mode == "none":
        return []
    result = []
    for aspect in aspects:
        if mode == "hard" and aspect.get("type") not in HARD_ASPECTS:
            continue
        if mode != "all" and aspect.get("first") not in planets and aspect.get("second") not in planets:
            continue
        result.append(aspect)
    return result


def _filter_chart_for_batch(
    chart: dict[str, Any] | None,
    focus: dict[str, Any],
) -> dict[str, Any] | None:
    if chart is None:
        return None
    planets = {
        name: data
        for name, data in (chart.get("planets") or {}).items()
        if name in focus["planets"]
        or (
            focus["houses"]
            and isinstance(data, dict)
            and data.get("house") in focus["houses"]
        )
    }
    if not planets:
        planets = dict(chart.get("planets") or {})
    filtered: dict[str, Any] = {
        "birth_date": chart.get("birth_date"),
        "birth_time_local": chart.get("birth_time_local"),
        "birth_time_utc": chart.get("birth_time_utc"),
        "timezone": chart.get("timezone"),
        "time_is_approximate": chart.get("time_is_approximate"),
        "ascendant": chart.get("ascendant"),
        "planets": planets,
        "aspects": _filter_aspects(chart.get("aspects") or [], focus),
    }
    if focus["keep_houses"] and "houses" in chart:
        filtered["houses"] = chart["houses"]
    return filtered


def _filter_career_hints(
    hints: dict[str, Any] | None,
    focus: dict[str, Any],
) -> dict[str, Any] | None:
    if not focus["career"] or not hints:
        return None
    planets = focus["planets"]
    houses = focus["houses"]
    planet_hints = [
        item
        for item in hints.get("planet_talent_hints") or []
        if item.get("planet") in planets
    ]
    house_hints = hints.get("active_house_professions") or []
    if houses:
        house_hints = [item for item in house_hints if item.get("house") in houses]
    return {
        "important": hints.get("important"),
        "active_house_professions": house_hints,
        "planet_talent_hints": planet_hints or list(hints.get("planet_talent_hints") or []),
    }


def build_batch_payload(
    payload: dict[str, Any],
    batch: list[dict[str, str]],
) -> dict[str, Any]:
    """Shrink structured chart context for one section batch, then render fact strings."""
    titles = [section["title"] for section in batch]
    focus = _merge_focus(titles)
    primary_chart = _filter_chart_for_batch(payload.get("primary_chart"), focus)
    partner_chart = _filter_chart_for_batch(payload.get("partner_chart"), focus)
    synastry_aspects = (
        _filter_aspects(payload.get("synastry_aspects") or [], focus)
        if focus["synastry"]
        else []
    )
    batch_payload = {
        "report_type": payload.get("report_type"),
        "language": payload.get("language"),
        "sections": batch,
        "primary_chart": primary_chart,
        "partner_chart": partner_chart,
        "synastry_aspects": synastry_aspects,
        "allowed_facts": _facts_from_prompt_charts(
            primary_chart,
            partner_chart,
            synastry_aspects,
            include_ascendant=focus["ascendant"],
        ),
    }
    career_hints = _filter_career_hints(payload.get("career_and_talent_hints"), focus)
    if career_hints is not None:
        batch_payload["career_and_talent_hints"] = career_hints
    return batch_payload


def _validate_batch(
    content: Any,
    expected_titles: list[str],
    allowed_facts: set[str],
) -> list[dict[str, Any]] | None:
    if not isinstance(content, dict):
        return None
    sections = content.get("sections")
    if not isinstance(sections, list) or [item.get("title") for item in sections] != expected_titles:
        return None
    normalized = []
    for section in sections:
        content_text = section.get("content")
        references = section.get("references")
        if (
            not isinstance(content_text, str)
            or len(content_text.split()) < 30
            or not isinstance(references, list)
        ):
            return None
        exact_references = [
            reference for reference in references
            if isinstance(reference, str) and reference in allowed_facts
        ]
        if not exact_references:
            return None
        normalized.append({
            "title": section["title"],
            "content": content_text.strip(),
            "references": exact_references[:3],
        })
    return normalized


def _report_shell(report_type: str) -> tuple[str, str]:
    titles = {
        "personality": "Ваш персональный разбор",
        "compatibility": "Потенциал вашей совместимости",
        "money": "Ваш денежный код",
    }
    intros = {
        "personality": "Ниже — ключевые символические темы вашей натальной карты.",
        "compatibility": "Ниже — ключевые символические темы взаимодействия вашей пары.",
        "money": "Ниже — ключевые символические темы вашего отношения к ресурсам и реализации.",
    }
    return titles[report_type], intros[report_type]


async def generate_report_content(
    report_type: str, chart: dict, second_chart: dict | None = None
) -> dict[str, Any] | None:
    """Generate independent section batches and combine their validated results."""
    if not settings.ai_api_key:
        return None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            timeout=AI_TIMEOUT_SECONDS,
            max_retries=0,
        )
        payload = build_prompt_payload(report_type, chart, second_chart)
        semaphore = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

        async def generate_batch(batch: list[dict[str, str]]) -> list[dict[str, Any]] | None:
            batch_payload = build_batch_payload(payload, batch)
            expected_titles = [section["title"] for section in batch]
            batch_allowed_facts = set(batch_payload["allowed_facts"])
            request_id = uuid4().hex
            for attempt in range(FAILED_BATCH_RETRIES + 1):
                try:
                    user_payload = json.dumps(batch_payload, ensure_ascii=False)
                    _save_payload_sample(
                        "request",
                        batch_payload,
                        report_type=report_type,
                        attempt=attempt + 1,
                        request_id=request_id,
                    )
                    async with semaphore:
                        response = await client.chat.completions.create(
                            model=settings.ai_model,
                            response_format={"type": "json_object"},
                            messages=[
                                {"role": "system", "content": SYSTEM_PROMPT},
                                {
                                    "role": "user",
                                    "content": user_payload,
                                },
                            ],
                        )
                    raw_content = response.choices[0].message.content
                    response_payload: Any = raw_content or ""
                    if raw_content:
                        try:
                            response_payload = json.loads(raw_content)
                        except json.JSONDecodeError:
                            pass
                    _save_payload_sample(
                        "response",
                        response_payload,
                        report_type=report_type,
                        attempt=attempt + 1,
                        request_id=request_id,
                    )
                    if raw_content:
                        validated = _validate_batch(
                            json.loads(raw_content),
                            expected_titles,
                            batch_allowed_facts,
                        )
                        if validated:
                            return validated
                    logger.warning(
                        "AI вернул неполный пакет разделов %s, попытка %s",
                        expected_titles,
                        attempt + 1,
                    )
                except (json.JSONDecodeError, TimeoutError, ValueError) as error:
                    logger.warning(
                        "Не удалось получить пакет разделов %s: %s",
                        expected_titles,
                        error,
                    )
                except Exception:
                    logger.exception(
                        "Неожиданная ошибка при генерации пакета разделов %s",
                        expected_titles,
                    )
            return None

        results = await asyncio.gather(
            *(generate_batch(batch) for batch in _section_batches(payload["sections"]))
        )
        if any(result is None for result in results):
            return None
        title, intro = _report_shell(report_type)
        return {
            "title": title,
            "intro": intro,
            "sections": [section for batch in results for section in batch],
            "disclaimer": (
                "Материал носит символический и развлекательный характер и "
                "предназначен для саморефлексии."
            ),
        }
    except (ImportError, ValueError) as error:
        logger.warning("Не удалось подготовить AI-отчёт: %s", error)
        return None
    except Exception:
        logger.exception("Неожиданная ошибка при сборке AI-отчёта")
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
