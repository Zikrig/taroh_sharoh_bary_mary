import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.astro import calculate_synastry
from config.settings import settings
from services.prompt_guides.career import build_career_hints
from services.reports_new import SECTIONS

logger = logging.getLogger(__name__)
AI_TIMEOUT_SECONDS = 240.0
MAX_PARALLEL_REQUESTS = 5
FAILED_BATCH_RETRIES = 2
PAYLOAD_SAMPLES_DIR = Path("data/payload_samples")
SECTION_HINTS_DIR = Path(__file__).resolve().parent.parent / "section_hints"
MAX_HINT_CARDS = 6
MAX_SELECTED_ASPECTS = 6
MAX_SECTION_SUMMARY_CHARS = 220
MAX_CACHED_SECTIONS = 512

# Phrases banned by the product brief: fatalism, guarantees and categorical claims.
FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"гарантирован", "гарантии результата"),
    (r"\bсуждено\b", "утверждение о судьбе"),
    (r"обречен|обречён", "утверждение о безысходности"),
    (r"(ты|вы|тебе|вам)\s+(точно|обязательно|наверняка|всегда|никогда)", "категоричное утверждение"),
    (r"(всегда|никогда)\s+(будешь|будете|сможешь|сможете)", "категоричное утверждение"),
    (r"обязательно\s+(будет|встрет|произойд|получ|станет)", "обещание события"),
    (r"100\s*%|сто процентов", "обещание вероятности"),
    (r"\bдиагноз", "медицинская формулировка"),
)

PERSONAL_PLANETS = frozenset({"Солнце", "Луна", "Меркурий", "Венера", "Марс"})
SOCIAL_PLANETS = frozenset({"Юпитер", "Сатурн"})
OUTER_PLANETS = frozenset({"Уран", "Нептун", "Плутон"})
ALL_PLANETS = PERSONAL_PLANETS | SOCIAL_PLANETS | OUTER_PLANETS
HARD_ASPECTS = frozenset({"квадрат", "оппозиция"})
ASPECT_ORBS = {
    "соединение": 8.0,
    "секстиль": 5.0,
    "квадрат": 6.0,
    "тригон": 6.0,
    "оппозиция": 8.0,
}
ASPECT_TYPE_WEIGHTS = {
    "соединение": 1.0,
    "оппозиция": 0.95,
    "квадрат": 0.9,
    "тригон": 0.75,
    "секстиль": 0.55,
}
PLANET_SIGNIFICANCE = {
    "Солнце": 1.0,
    "Луна": 1.0,
    "Меркурий": 0.8,
    "Венера": 0.85,
    "Марс": 0.85,
    "Юпитер": 0.65,
    "Сатурн": 0.8,
    "Уран": 0.5,
    "Нептун": 0.5,
    "Плутон": 0.55,
}

# Per-section focus: which facts/chart pieces a batch actually needs.
# "aspects": "involving" | "all" | "hard" | "none"
_FOCUS_PERSONAL = {
    "planets": PERSONAL_PLANETS,
    "ascendant": True,
    "aspects": "involving",
}
_FOCUS_ALL = {
    "planets": ALL_PLANETS,
    "ascendant": True,
    "aspects": "all",
    "keep_houses": True,
}
_FOCUS_LOVE = {
    "planets": frozenset({"Венера", "Луна", "Марс", "Солнце"}),
    "houses": frozenset({5, 7}),
    "ascendant": True,
    "aspects": "involving",
}
_FOCUS_MONEY = {
    "planets": frozenset({"Венера", "Юпитер", "Сатурн", "Солнце", "Марс", "Меркурий"}),
    "houses": frozenset({2, 6, 8, 10}),
    "aspects": "involving",
    "career": True,
    "keep_houses": True,
}
_FOCUS_CAREER = {
    "planets": ALL_PLANETS,
    "houses": frozenset({2, 6, 10}),
    "aspects": "involving",
    "career": True,
    "keep_houses": True,
}
_FOCUS_SYNASTRY = {
    "planets": ALL_PLANETS,
    "aspects": "involving",
    "synastry": True,
    "ascendant": True,
}

SECTION_CONTEXT_FOCUS: dict[str, dict[str, Any]] = {
    # personality_free
    "Твой портрет": _FOCUS_PERSONAL,
    "Какой ты человек": _FOCUS_PERSONAL,
    "Как тебя видят другие": {**_FOCUS_PERSONAL, "ascendant": True},
    "Твои сильные стороны": _FOCUS_ALL,
    "Что может тебе мешать": {**_FOCUS_ALL, "aspects": "hard"},
    "Скрытая сторона": {**_FOCUS_ALL, "aspects": "hard"},
    "Любовь": _FOCUS_LOVE,
    "Деньги и работа": _FOCUS_MONEY,
    "Главная точка роста": {**_FOCUS_ALL, "career": True},
    # personality full
    "Твой главный психологический портрет": _FOCUS_PERSONAL,
    "Твой внутренний мир": {
        "planets": frozenset({"Луна", "Нептун", "Венера", "Солнце"}),
        "ascendant": True,
        "aspects": "involving",
    },
    "Как тебя видят люди": {**_FOCUS_PERSONAL, "ascendant": True},
    "Твои сложные стороны": {**_FOCUS_ALL, "aspects": "hard"},
    "Твои скрытые качества": _FOCUS_ALL,
    "Твоё мышление": {
        "planets": frozenset({"Меркурий", "Солнце", "Уран", "Сатурн"}),
        "aspects": "involving",
    },
    "Эмоции и стресс": {
        "planets": frozenset({"Луна", "Марс", "Сатурн", "Нептун"}),
        "aspects": "involving",
    },
    "Ты в любви": _FOCUS_LOVE,
    "Твои повторяющиеся сценарии": {**_FOCUS_ALL, "aspects": "hard"},
    "Какой партнёр тебе подходит": _FOCUS_LOVE,
    "С кем тебе может быть сложно": {**_FOCUS_LOVE, "aspects": "hard"},
    "Денежный профиль": _FOCUS_MONEY,
    "Карьера и реализация": _FOCUS_CAREER,
    "Профессиональные направления": _FOCUS_CAREER,
    "Главные блоки": {**_FOCUS_ALL, "aspects": "hard"},
    "Точки роста": {**_FOCUS_ALL, "career": True},
    "Что ты можешь не замечать в себе": _FOCUS_ALL,
    "Практические рекомендации": {**_FOCUS_ALL, "career": True},
    "Итоговый профиль": _FOCUS_ALL,
    # love
    "Как ты влюбляешься": _FOCUS_LOVE,
    "Что вызывает притяжение": _FOCUS_LOVE,
    "Что важно чувствовать в отношениях": _FOCUS_LOVE,
    "Как ты проявляешь любовь": _FOCUS_LOVE,
    "Как ты хочешь получать любовь": _FOCUS_LOVE,
    "Что вызывает недоверие": {**_FOCUS_LOVE, "aspects": "hard"},
    "Как проявляется ревность": {**_FOCUS_LOVE, "aspects": "hard"},
    "Реакция на дистанцию": _FOCUS_LOVE,
    "Ты в конфликтах": {**_FOCUS_LOVE, "aspects": "hard"},
    "Что трудно сказать партнёру": _FOCUS_LOVE,
    "Как ты переживаешь расставание": {**_FOCUS_LOVE, "aspects": "hard"},
    "Возвращение к прошлому": _FOCUS_LOVE,
    "Повторяющиеся сценарии отношений": {**_FOCUS_LOVE, "aspects": "hard"},
    "С кем может быть сложно": {**_FOCUS_LOVE, "aspects": "hard"},
    "Что усиливает отношения": _FOCUS_LOVE,
    "Что может разрушать отношения": {**_FOCUS_LOVE, "aspects": "hard"},
    "Итоговый любовный портрет": _FOCUS_LOVE,
    # compatibility
    "Общая динамика пары": _FOCUS_SYNASTRY,
    "Эмоциональная совместимость": {
        "planets": frozenset({"Луна"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Притяжение": {
        "planets": frozenset({"Венера", "Марс", "Солнце"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Общение": {
        "planets": frozenset({"Меркурий", "Луна"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Интеллектуальная совместимость": {
        "planets": frozenset({"Меркурий"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Доверие": {**_FOCUS_SYNASTRY, "aspects": "hard"},
    "Ревность": {
        "planets": frozenset({"Венера", "Марс", "Луна", "Плутон"}),
        "aspects": "hard",
        "synastry": True,
    },
    "Личные границы": {
        "planets": frozenset({"Сатурн", "Луна", "Уран"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Конфликты": {**_FOCUS_SYNASTRY, "aspects": "hard"},
    "Что одного притягивает в другом": _FOCUS_SYNASTRY,
    "Что может раздражать": {**_FOCUS_SYNASTRY, "aspects": "hard"},
    "Что каждому нужно от другого": _FOCUS_SYNASTRY,
    "Сильные стороны пары": _FOCUS_SYNASTRY,
    "Сложные стороны": {**_FOCUS_SYNASTRY, "aspects": "hard"},
    "Повторяющиеся сценарии": {**_FOCUS_SYNASTRY, "aspects": "hard"},
    "Как вам лучше общаться": {
        "planets": frozenset({"Меркурий", "Луна", "Венера"}),
        "aspects": "involving",
        "synastry": True,
    },
    "Как улучшить отношения": _FOCUS_SYNASTRY,
    "Итоговый портрет пары": _FOCUS_SYNASTRY,
    # money
    "Отношение к деньгам": _FOCUS_MONEY,
    "Что мотивирует зарабатывать": _FOCUS_MONEY,
    "Отношение к стабильности": {
        "planets": frozenset({"Сатурн", "Венера", "Луна"}),
        "houses": frozenset({2, 8}),
        "aspects": "involving",
        "career": True,
    },
    "Отношение к риску": {
        "planets": frozenset({"Марс", "Уран", "Юпитер", "Сатурн"}),
        "aspects": "involving",
        "career": True,
    },
    "Отношение к ответственности": {
        "planets": frozenset({"Сатурн", "Солнце", "Марс"}),
        "aspects": "involving",
        "career": True,
    },
    "Работа в команде": {
        "planets": frozenset({"Меркурий", "Венера", "Луна", "Солнце"}),
        "houses": frozenset({6, 7, 11}),
        "aspects": "involving",
        "career": True,
    },
    "Предпринимательский потенциал": _FOCUS_CAREER,
    "Что может мешать финансовому росту": {**_FOCUS_MONEY, "aspects": "hard"},
    "Качества, которые можно монетизировать": _FOCUS_CAREER,
    "Подходящий рабочий формат": _FOCUS_CAREER,
    "Подходящая рабочая среда": _FOCUS_CAREER,
    "Риск выгорания": {
        "planets": frozenset({"Марс", "Сатурн", "Луна", "Солнце"}),
        "aspects": "hard",
        "career": True,
    },
    "Навыки для развития": _FOCUS_CAREER,
    "Подходящие направления": _FOCUS_CAREER,
    "Почему эти направления подходят": _FOCUS_CAREER,
    "Что может мешать реализации": {**_FOCUS_CAREER, "aspects": "hard"},
    "Итоговый денежный профиль": _FOCUS_MONEY,
}
DEFAULT_SECTION_FOCUS = {
    "planets": frozenset({"Солнце", "Луна"}),
    "ascendant": True,
    "aspects": "involving",
}

SYSTEM_PROMPT = """
Ты — автор одного раздела персонального отчёта. Пиши строго на русском языке,
на «вы», живо, бережно и конкретно.

Всегда используйте живые, обычные формулировки: как в спокойном разговоре с умным
человеком, а не как в шаблоне, презентации или «нейросетевом» тексте. Избегайте
канцелярита, пафоса, пустых обобщений и однотипных конструкций вроде
«вы склонны», «для вас важно», «это проявляется в том, что» на каждом предложении.
Пишите естественно, с разной длиной фраз и конкретными бытовыми деталями.

Переданные facts и interpretation_hints — внутренние опоры для рассуждения.
Используй только их, но никогда не раскрывай технический источник вывода.

Строгий запрет для итогового текста раздела: не упоминай астрологию, карту, планеты,
Солнце, Луну, знаки зодиака, дома, аспекты, соединения, тригоны, квадраты, оппозиции,
положения или расчёты. Не пиши «Солнце в Раке» и аналогичные формулировки.

— выберите 2–4 наиболее значимые внутренние опоры для темы раздела;
— переводите их в наблюдаемые черты, привычки, реакции и жизненные ситуации;
— interpretation_hints — это смысловые опоры, а не готовые фразы: используйте 1–3
релевантные подсказки, переформулируйте их и не копируйте дословно;
— если передан covered_sections, не повторяйте мысли, примеры и формулировки уже написанных
разделов: раскрывайте тему с новой стороны;
— сначала покажите паттерн, затем его возможное проявление в жизни;
— min_words и max_words в requirements — рекомендуемый объём текста, не оформляйте их в тексте;
— в темах карьеры, дохода и способностей называйте 2–4 конкретные роли, сферы, задачи или
рабочие среды, а не общие слова вроде «творческая работа».

Не давайте советов, рекомендаций, планов действий и инструкций «как исправить».
Не пишите «вам стоит», «лучше», «попробуйте», «рекомендуется», «имеет смысл»,
«найдите баланс», «обратите внимание». Описывайте, а не наставляйте.
Исключение: только если название раздела прямо про практические рекомендации —
тогда мягкие наблюдения-ориентиры допустимы.

Не давайте диагнозов, медицинских назначений, юридических или инвестиционных советов.
Не гарантируйте доход, отношения или будущие события. Не используйте «гарантированно»,
«суждено», «обречён», «100%», «вы всегда», «вы никогда», «вы точно», «вам обязательно».

Верните только текст раздела: без JSON, Markdown, заголовка, ссылок на факты, символов ** и комментариев.
""".strip()

SECTION_GUIDANCE = {
    "personality_free": {
        "Твой портрет": "4–6 предложений цельного портрета без перечисления черт списком",
        "Твои сильные стороны": "3 главных качества: что это, как проявляется, где помогает",
        "Что может тебе мешать": "3 сложности без критики; покажите оборот сильной черты",
        "Скрытая сторона": "2–3 внутренних противоречия, эмоционально точно",
        "Любовь": "как влюбляется, что важно получать и что отталкивает",
        "Деньги и работа": "мотивация, формат работы и отношение к риску без гарантий дохода",
        "Главная точка роста": "одно ясное направление роста как наблюдение, без советов и инструкций",
    },
    "love_free": {
        "Как ты влюбляешься": "3–4 предложения о процессе влюблённости через реальные ситуации",
        "Что вызывает притяжение": "2–3 конкретных типа притяжения без идеализации партнёра",
        "Что важно чувствовать в отношениях": "эмоциональные потребности и ощущение безопасности",
        "Ты в конфликтах": "стиль спора и восстановления контакта без обвинений",
        "Какой партнёр тебе подходит": "характер и стиль отношений, не только знаки",
        "Что может разрушать отношения": "риски и зоны внимания без фатализма",
        "Итоговый любовный портрет": "короткая сводка без предсказаний встречи или разрыва",
    },
    "compatibility_free": {
        "Эмоциональная совместимость": "как пара проживает чувства и поддержку",
        "Притяжение": "химия и интерес друг к другу без процента совместимости",
        "Сложные стороны": "главная зона напряжения без обвинений",
        "Общая динамика пары": "целостная картина взаимодействия и темы для углубления",
    },
    "money_free": {
        "Отношение к деньгам": "как воспринимаются деньги и ресурсы",
        "Что мотивирует зарабатывать": "2–3 драйвера дохода без обещаний богатства",
        "Отношение к риску": "готовность к неопределённости и переменам",
        "Подходящие направления": "2–3 конкретные сферы или роли без гарантии дохода",
        "Что может мешать финансовому росту": "привычки и установки без критики личности",
        "Главная точка роста": "одно ясное направление развития как наблюдение, без советов",
    },
    "personality": {
        "Твой главный психологический портрет": "целостный портрет и главное противоречие характера",
        "Твои сильные стороны": "5–7 качеств: проявление → польза → обратная сторона",
        "Твои сложные стороны": "5–7 сложностей с путём превращения в ресурс",
        "Твои скрытые качества": "до 7 неожиданных наблюдений",
        "Ты в любви": "подробно: влюблённость, ревность, дистанция, конфликт, расставание",
        "Твои повторяющиеся сценарии": "3–5 сценариев с шагами как изменить",
        "Профессиональные направления": "8–12 направлений: название, почему подходит, формат",
        "Практические рекомендации": "7–10 конкретных рекомендаций по карте",
        "Итоговый профиль": "единый портрет и оригинальная фраза профиля",
    },
    "love": {
        "Как ты влюбляешься": "процесс влюблённости через реальные ситуации",
        "Итоговый любовный портрет": "сводка без предсказаний встречи или разрыва",
    },
    "compatibility": {
        "Общая динамика пары": "динамика без процента совместимости",
        "Итоговый портрет пары": "сводка без «идеальная пара» и без фатализма",
    },
    "money": {
        "Подходящие направления": "конкретные роли и сферы без гарантии дохода",
        "Почему эти направления подходят": "свяжите каждое направление с фактами карты",
        "Итоговый денежный профиль": "сводка без обещания богатства и без инвестсоветов",
    },
}
DEFAULT_SECTION_GUIDANCE = (
    "выберите 2–4 наиболее важных факта, прямо связанных с темой раздела, "
    "и объясните их как единый символический паттерн без перечисления всей карты"
)
PLANET_CODES = {
    "Солнце": "sun",
    "Луна": "moon",
    "Меркурий": "mercury",
    "Венера": "venus",
    "Марс": "mars",
    "Юпитер": "jupiter",
    "Сатурн": "saturn",
    "Уран": "uranus",
    "Нептун": "neptune",
    "Плутон": "pluto",
}
SIGN_CODES = {
    "Овен": "aries",
    "Телец": "taurus",
    "Близнецы": "gemini",
    "Рак": "cancer",
    "Лев": "leo",
    "Дева": "virgo",
    "Весы": "libra",
    "Скорпион": "scorpio",
    "Стрелец": "sagittarius",
    "Козерог": "capricorn",
    "Водолей": "aquarius",
    "Рыбы": "pisces",
}
ASPECT_CODES = {
    "соединение": "conjunction",
    "секстиль": "sextile",
    "квадрат": "square",
    "тригон": "trine",
    "оппозиция": "opposition",
}
_SECTION_HINT_INDEX: dict[tuple[str, str], Path] | None = None
_SECTION_CACHE: dict[str, dict[str, Any]] = {}


def _save_payload_sample(
    kind: str,
    payload: Any,
    *,
    report_type: str,
    attempt: int,
    request_id: str,
) -> None:
    """Persist the exact request/response text used with the model."""
    if not settings.save_payload_samples:
        return
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
    use_labels: bool = True,
) -> list[str]:
    """Render citation strings from structured chart JSON for the prompt."""
    facts: list[str] = []
    # If not compatibility, we don't need "Карта 1:" prefix
    charts = [("Карта 1", primary_chart)]
    if use_labels:
        charts.append(("Карта 2", partner_chart))
    else:
        # Only primary chart, no prefix
        charts = [("", primary_chart)]

    for label_prefix, chart in charts:
        if chart is None:
            continue
        label = f"{label_prefix}: " if label_prefix else ""
        for planet, position in (chart.get("planets") or {}).items():
            facts.append(
                f"{label}{planet} в {position['sign']}, дом {position['house']}"
            )
        if include_ascendant and chart.get("ascendant"):
            facts.append(f"{label}Асцендент в {chart['ascendant']['sign']}")
        for aspect in chart.get("aspects") or []:
            facts.append(
                f"{label}{aspect['first']} {aspect['type']} {aspect['second']}"
            )
    for aspect in synastry_aspects or []:
        facts.append(
            f"Синастрия: {aspect['first']} {aspect['type']} {aspect['second']}"
        )
    return facts


def _allowed_facts(chart: dict, second_chart: dict | None, report_type: str) -> list[str]:
    return _facts_from_prompt_charts(
        _chart_for_prompt(chart),
        _chart_for_prompt(second_chart) if second_chart else None,
        calculate_synastry(chart, second_chart) if second_chart else [],
        include_ascendant=True,
        use_labels=(report_type == "compatibility"),
    )


def build_prompt_payload(report_type: str, chart: dict, second_chart: dict | None) -> dict[str, Any]:
    if report_type not in SECTIONS:
        raise ValueError(f"Неизвестный тип отчёта: {report_type}")
    if report_type in ("compatibility", "compatibility_free") and second_chart is None:
        raise ValueError("Для отчёта о совместимости нужны обе карты.")
    primary_chart = _chart_for_prompt(chart)
    partner_chart = _chart_for_prompt(second_chart) if second_chart else None
    synastry_aspects = calculate_synastry(chart, second_chart) if second_chart else []
    use_labels = report_type in ("compatibility", "compatibility_free")
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
            use_labels=use_labels,
        ),
        "career_and_talent_hints": build_career_hints(
            chart,
            include_houses=True,
        ),
    }
    return payload


def _section_batches(sections: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    """Compatibility helper: production sends exactly one section per request."""
    return [[section] for section in sections]


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
    """Keep only the strongest thematic aspects for one report section."""
    mode = focus["aspects"]
    planets = focus["planets"]
    if mode == "none":
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for aspect in aspects:
        if mode == "hard" and aspect.get("type") not in HARD_ASPECTS:
            continue
        if mode != "all" and aspect.get("first") not in planets and aspect.get("second") not in planets:
            continue
        aspect_type = aspect.get("type")
        max_orb = ASPECT_ORBS.get(aspect_type)
        orb = aspect.get("orb")
        if max_orb is None or not isinstance(orb, (int, float)) or orb > max_orb:
            continue
        exactness = 1 - (orb / max_orb)
        planet_weight = (
            PLANET_SIGNIFICANCE.get(aspect.get("first"), 0.4)
            + PLANET_SIGNIFICANCE.get(aspect.get("second"), 0.4)
        ) / 2
        score = (
            exactness * 0.65
            + ASPECT_TYPE_WEIGHTS.get(aspect_type, 0.4) * 0.2
            + planet_weight * 0.15
        )
        scored.append((score, aspect))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [aspect for _, aspect in scored[:MAX_SELECTED_ASPECTS]]


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
    report_type = payload.get("report_type")
    focus = _merge_focus(titles)
    primary_chart = _filter_chart_for_batch(payload.get("primary_chart"), focus)
    partner_chart = _filter_chart_for_batch(payload.get("partner_chart"), focus)
    synastry_aspects = (
        _filter_aspects(payload.get("synastry_aspects") or [], focus)
        if focus["synastry"]
        else []
    )
    batch_payload = {
        "report_type": report_type,
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
            use_labels=(report_type == "compatibility"),
        ),
    }
    career_hints = _filter_career_hints(payload.get("career_and_talent_hints"), focus)
    if career_hints is not None:
        batch_payload["career_and_talent_hints"] = career_hints
    return batch_payload


def _section_hint_paths() -> dict[tuple[str, str], Path]:
    global _SECTION_HINT_INDEX
    if _SECTION_HINT_INDEX is not None:
        return _SECTION_HINT_INDEX
    try:
        index = json.loads((SECTION_HINTS_DIR / "index.json").read_text(encoding="utf-8"))
        _SECTION_HINT_INDEX = {
            (item["report_type"], item["title_ru"]): SECTION_HINTS_DIR / item["path"]
            for item in index["sections"]
        }
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"Не удалось загрузить JSON-подсказки разделов: {error}") from error
    return _SECTION_HINT_INDEX


def _load_section_hint(report_type: str, title: str) -> dict[str, Any]:
    path = _section_hint_paths().get((report_type, title))
    if path is None:
        raise ValueError(f"Не найдена JSON-подсказка для раздела «{title}».")
    try:
        hint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Не удалось прочитать JSON-подсказку {path.name}: {error}") from error
    if hint.get("report_type") != report_type or hint.get("title_ru") != title:
        raise ValueError(f"Некорректная JSON-подсказка для раздела «{title}».")
    return hint


def _canonical_facts(section_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build code-based facts while keeping Russian text only for the model."""
    facts: list[dict[str, Any]] = []
    charts = (
        ("primary", section_payload.get("primary_chart")),
        ("partner", section_payload.get("partner_chart")),
    )
    for scope, chart in charts:
        if chart is None:
            continue
        label = "Карта 1: " if scope == "primary" and section_payload["report_type"] == "compatibility" else ""
        if scope == "partner":
            label = "Карта 2: "
        for planet, position in (chart.get("planets") or {}).items():
            planet_code = PLANET_CODES.get(planet)
            sign_code = SIGN_CODES.get(position.get("sign"))
            if not planet_code or not sign_code:
                continue
            facts.append({
                "id": f"{scope}.planet.{planet_code}.sign.{sign_code}",
                "scope": scope,
                "kind": "planet_sign",
                "planet": planet_code,
                "sign": sign_code,
                "house": position.get("house"),
                "text_ru": f"{label}{planet} в {position['sign']}, дом {position['house']}",
            })
        ascendant = chart.get("ascendant") or {}
        ascendant_sign = SIGN_CODES.get(ascendant.get("sign"))
        if ascendant_sign:
            facts.append({
                "id": f"{scope}.ascendant.{ascendant_sign}",
                "scope": scope,
                "kind": "ascendant",
                "sign": ascendant_sign,
                "text_ru": f"{label}Асцендент в {ascendant['sign']}",
            })
        for aspect in chart.get("aspects") or []:
            first_code = PLANET_CODES.get(aspect.get("first"))
            second_code = PLANET_CODES.get(aspect.get("second"))
            aspect_code = ASPECT_CODES.get(aspect.get("type"))
            if not first_code or not second_code or not aspect_code:
                continue
            facts.append({
                "id": f"{scope}.aspect.{first_code}.{aspect_code}.{second_code}",
                "scope": scope,
                "kind": "aspect",
                "first": first_code,
                "second": second_code,
                "aspect": aspect_code,
                "text_ru": f"{label}{aspect['first']} {aspect['type']} {aspect['second']}",
            })
    for aspect in section_payload.get("synastry_aspects") or []:
        first_code = PLANET_CODES.get(aspect.get("first"))
        second_code = PLANET_CODES.get(aspect.get("second"))
        aspect_code = ASPECT_CODES.get(aspect.get("type"))
        if not first_code or not second_code or not aspect_code:
            continue
        facts.append({
            "id": f"synastry.{first_code}.{aspect_code}.{second_code}",
            "kind": "synastry_aspect",
            "first": first_code,
            "second": second_code,
            "aspect": aspect_code,
            "text_ru": f"Синастрия: {aspect['first']} {aspect['type']} {aspect['second']}",
        })
    return facts


def _card_priority(card: dict[str, Any]) -> int:
    priority = card.get("priority")
    return priority if isinstance(priority, int) else 0


def _selected_hint_cards(hint: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    for card in hint.get("hint_cards") or []:
        text = card.get("text_ru")
        if not isinstance(text, str) or not text.strip():
            continue
        condition = card.get("when") or {}
        if not condition or any(
            all(fact.get(key) == value for key, value in condition.items())
            for fact in facts
        ):
            selected.append(card)
    selected.sort(key=_card_priority, reverse=True)
    # Always keep explicit high-priority cards, but vary generic cards so
    # different reports do not receive an identical set of wordings.
    fixed = [card for card in selected if _card_priority(card) > 0]
    candidates = [card for card in selected if _card_priority(card) <= 0]
    remaining = max(0, MAX_HINT_CARDS - len(fixed))
    if len(candidates) > remaining:
        candidates = random.sample(candidates, remaining)
    return fixed[:MAX_HINT_CARDS] + candidates


def build_section_payload(
    payload: dict[str, Any],
    section: dict[str, str],
    covered_sections: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build the full prompt context for exactly one report section."""
    section_payload = build_batch_payload(payload, [section])
    hint = _load_section_hint(payload["report_type"], section["title"])
    facts = _canonical_facts(section_payload)
    selected_cards = _selected_hint_cards(hint, facts)
    requirements = hint.get("prompt_requirements") or {}
    built = {
        "report_type": payload["report_type"],
        "section": {
            "id": hint["section_id"],
            "title": hint["title_ru"],
            "brief": hint.get("brief", section["brief"]),
            "guidance": section["guidance"],
            "requirements": requirements,
        },
        "facts": facts,
        "allowed_facts": section_payload["allowed_facts"],
        "interpretation_hints": [card["text_ru"] for card in selected_cards],
        "career_and_talent_hints": section_payload.get("career_and_talent_hints"),
        "time_is_approximate": bool(
            (section_payload.get("primary_chart") or {}).get("time_is_approximate")
        ),
    }
    if covered_sections:
        built["covered_sections"] = covered_sections
    return built


def _normalize_fact(text: str) -> str:
    """Remove noise from a fact string for robust comparison."""
    if not isinstance(text, str):
        return ""
    # Remove dots, extra spaces and convert to lower case
    clean = re.sub(r"[.\s]+", "", text).lower()
    # Replace common Latin lookalikes with Cyrillic to avoid encoding mixups
    replacements = str.maketrans("abcekmnoprtuxy", "авсекмнорртуху")
    return clean.translate(replacements)


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

    normalized_allowed = {
        _normalize_fact(fact): fact for fact in allowed_facts
    }

    normalized_results = []
    for section in sections:
        content_text = section.get("content")
        references = section.get("references")
        if (
            not isinstance(content_text, str)
            or len(content_text.split()) < 30
            or not isinstance(references, list)
        ):
            return None

        # Robust reference matching
        exact_references = []
        for ref in references:
            if not isinstance(ref, str):
                continue
            norm_ref = _normalize_fact(ref)
            if norm_ref in normalized_allowed:
                # Use the original string from allowed_facts, not the AI's version
                exact_references.append(normalized_allowed[norm_ref])

        if not exact_references:
            # If AI couldn't provide any valid reference, fail this section
            return None

        normalized_results.append({
            "title": section["title"],
            "content": content_text.strip(),
            "references": exact_references[:3],
        })
    return normalized_results


def _forbidden_phrases(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for pattern, label in FORBIDDEN_PATTERNS:
        if re.search(pattern, lowered) and label not in found:
            found.append(label)
    return found


def _validate_section(
    content: Any,
    section: dict[str, Any],
    allowed_facts: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Check one plain-text section and explain why it was rejected."""
    if not isinstance(content, str) or not content.strip():
        return None, "модель вернула пустой ответ"
    normalized = re.sub(r"\*\*(.*?)\*\*", r"\1", content.strip(), flags=re.DOTALL)
    normalized = normalized.replace("**", "")
    requirements = section.get("requirements") or {}
    min_words = requirements.get("min_words", 30)
    word_count = len(normalized.split())
    if word_count < min_words:
        return None, f"в тексте {word_count} слов, нужно не меньше {min_words}"
    # forbidden = _forbidden_phrases(normalized)
    # if forbidden:
    #     return None, "недопустимые формулировки: " + ", ".join(forbidden)
    return {
        "title": section["title"],
        "content": normalized,
        # References are selected by the application, not requested from the model.
        "references": allowed_facts[:3],
    }, None


def _section_summary(text: str) -> str:
    """Condense a finished section so later sections can avoid repeating it."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= MAX_SECTION_SUMMARY_CHARS:
        return collapsed
    trimmed = collapsed[:MAX_SECTION_SUMMARY_CHARS].rsplit(" ", 1)[0]
    return f"{trimmed}…"


def _section_cache_key(section_payload: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "report_type": section_payload["report_type"],
            "section": section_payload["section"],
            "facts": [fact["id"] for fact in section_payload["facts"]],
            "hints": section_payload["interpretation_hints"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return sha1(material.encode("utf-8")).hexdigest()


def _remember_section(key: str, section: dict[str, Any]) -> None:
    """Keep validated sections so a repeated report request does not pay for them twice."""
    if key in _SECTION_CACHE:
        return
    while len(_SECTION_CACHE) >= MAX_CACHED_SECTIONS:
        _SECTION_CACHE.pop(next(iter(_SECTION_CACHE)))
    _SECTION_CACHE[key] = section


def _report_shell(report_type: str) -> tuple[str, str]:
    titles = {
        "personality_free": "Ваш бесплатный персональный разбор",
        "love_free": "Ваш бесплатный любовный мини-разбор",
        "compatibility_free": "Ваш бесплатный мини-разбор пары",
        "money_free": "Ваш бесплатный денежный мини-разбор",
        "personality": "Ваш персональный разбор",
        "love": "Ваш любовный портрет",
        "compatibility": "Потенциал вашей совместимости",
        "money": "Ваш денежный код",
    }
    intros = {
        "personality_free": "Ниже — короткий символический портрет по вашей натальной карте.",
        "love_free": "Ниже — короткий символический портрет вашего стиля любви и близости.",
        "compatibility_free": "Ниже — короткий символический взгляд на динамику вашей пары.",
        "money_free": "Ниже — короткий символический портрет вашего отношения к ресурсам и реализации.",
        "personality": "Ниже — ключевые символические темы вашей натальной карты.",
        "love": "Ниже — ключевые символические темы вашего стиля любви и близости.",
        "compatibility": "Ниже — ключевые символические темы взаимодействия вашей пары.",
        "money": "Ниже — ключевые символические темы вашего отношения к ресурсам и реализации.",
    }
    return titles[report_type], intros[report_type]


async def generate_report_content(
    report_type: str, chart: dict, second_chart: dict | None = None
) -> dict[str, Any] | None:
    """Generate independent sections concurrently and combine their text."""
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

        async def generate_section(
            section: dict[str, str],
            covered_sections: list[dict[str, str]],
        ) -> dict[str, Any] | None:
            section_payload = build_section_payload(payload, section, covered_sections)
            cache_key = _section_cache_key(section_payload)
            cached = _SECTION_CACHE.get(cache_key)
            if cached:
                return cached
            request_id = uuid4().hex
            rejection: str | None = None
            for attempt in range(FAILED_BATCH_RETRIES + 1):
                try:
                    messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(section_payload, ensure_ascii=False),
                        },
                    ]
                    if rejection:
                        messages.append({
                            "role": "user",
                            "content": (
                                f"Предыдущий вариант отклонён: {rejection}. "
                                "Исправь именно это и верни только текст раздела."
                            ),
                        })
                    _save_payload_sample(
                        "request",
                        {
                            "model": settings.ai_model,
                            "temperature": settings.ai_temperature,
                            "presence_penalty": settings.ai_presence_penalty,
                            "frequency_penalty": settings.ai_frequency_penalty,
                            "messages": messages,
                        },
                        report_type=report_type,
                        attempt=attempt + 1,
                        request_id=request_id,
                    )
                    async with semaphore:
                        response = await client.chat.completions.create(
                            model=settings.ai_model,
                            messages=messages,
                            temperature=settings.ai_temperature,
                            presence_penalty=settings.ai_presence_penalty,
                            frequency_penalty=settings.ai_frequency_penalty,
                        )
                    raw_content = response.choices[0].message.content
                    _save_payload_sample(
                        "response",
                        {
                            "content": raw_content or "",
                            "word_count": len((raw_content or "").split()),
                        },
                        report_type=report_type,
                        attempt=attempt + 1,
                        request_id=request_id,
                    )
                    validated, rejection = _validate_section(
                        raw_content,
                        section_payload["section"],
                        section_payload["allowed_facts"],
                    )
                    if validated:
                        _remember_section(cache_key, validated)
                        return validated
                    logger.warning(
                        "AI вернул некорректный текст раздела «%s», попытка %s: %s",
                        section["title"],
                        attempt + 1,
                        rejection,
                    )
                except (TimeoutError, ValueError) as error:
                    logger.warning(
                        "Не удалось получить раздел «%s»: %s",
                        section["title"],
                        error,
                    )
                except Exception:
                    logger.exception(
                        "Неожиданная ошибка при генерации раздела «%s»",
                        section["title"],
                    )
            return None

        sections = payload["sections"]
        results: list[dict[str, Any]] = []
        covered: list[dict[str, str]] = []
        # Waves keep the existing concurrency limit while letting each section
        # see what previous sections already covered.
        for start in range(0, len(sections), MAX_PARALLEL_REQUESTS):
            wave = sections[start:start + MAX_PARALLEL_REQUESTS]
            snapshot = list(covered)
            wave_results = await asyncio.gather(
                *(generate_section(section, snapshot) for section in wave)
            )
            if any(result is None for result in wave_results):
                return None
            results.extend(wave_results)
            covered.extend(
                {"title": result["title"], "summary": _section_summary(result["content"])}
                for result in wave_results
            )
        title, intro = _report_shell(report_type)
        return {
            "title": title,
            "intro": intro,
            "sections": results,
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
