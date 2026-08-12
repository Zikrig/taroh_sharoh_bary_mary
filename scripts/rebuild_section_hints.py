"""Rebuild section_hints with cards scoped to each section's chart focus."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if "swisseph" not in sys.modules:
    sys.modules["swisseph"] = SimpleNamespace(
        SUN=0, MOON=1, MERCURY=2, VENUS=3, MARS=4, JUPITER=5,
        SATURN=6, URANUS=7, NEPTUNE=8, PLUTO=9,
    )

from services.ai import (  # noqa: E402
    ASPECT_CODES,
    DEFAULT_SECTION_FOCUS,
    PLANET_CODES,
    SECTION_CONTEXT_FOCUS,
    SIGN_CODES,
)
from services.reports_new import SECTIONS  # noqa: E402

HINTS_DIR = PROJECT_ROOT / "section_hints"
WORD_LIMITS = {
    "personality_free": (60, 100),
    "personality": (150, 250),
    "love": (150, 250),
    "money": (150, 250),
    "compatibility": (150, 250),
}

SIGN_ORDER = list(SIGN_CODES.keys())
PLANET_ORDER = list(PLANET_CODES.keys())
ASPECT_ORDER = list(ASPECT_CODES.keys())
ASPECT_ANGLES = {
    "conjunction": 0,
    "sextile": 60,
    "square": 90,
    "trine": 120,
    "opposition": 180,
}
MAX_SEPARATION = {
    frozenset({"sun", "mercury"}): 28,
    frozenset({"sun", "venus"}): 48,
    frozenset({"mercury", "venus"}): 76,
}

FILLED_BLURBS = {
    "sun": {
        "aries": (
            "Солнце в Овне связывают с инициативой и потребностью начинать "
            "самостоятельно. Показывайте как склонность, не как приговор."
        ),
        "leo": (
            "Солнце во Льве связывают с потребностью в признании и творческом "
            "самовыражении. Важно не сводить это к эгоцентризму."
        ),
    },
    "moon": {
        "cancer": (
            "Луна в Раке часто описывает потребность в безопасности и "
            "эмоциональной близости. Говорите бережно, без инфантилизации."
        ),
        "scorpio": (
            "Луна в Скорпионе связывают с интенсивными чувствами и потребностью "
            "в глубоком доверии. Избегайте драматизации."
        ),
    },
    "mercury": {
        "virgo": (
            "Меркурий в Деве связывают с аналитичностью и вниманием к деталям. "
            "Показывайте как стиль мышления, не как педантизм."
        ),
    },
    "venus": {
        "libra": (
            "Венера в Весах связывают с ценностью гармонии, диалога и взаимности "
            "в отношениях и выборе."
        ),
        "taurus": (
            "Венера в Тельце связывают с потребностью в стабильности, телесном "
            "комфорте и надёжных ценностях."
        ),
    },
    "mars": {
        "aries": (
            "Марс в Овне связывают с прямой энергией действия и быстрой реакцией. "
            "Показывайте как стиль инициативы, не как агрессию."
        ),
        "scorpio": (
            "Марс в Скорпионе связывают с упорством и сильной волей в конфликтных "
            "темах. Без фатализма и угроз."
        ),
    },
    "jupiter": {
        "sagittarius": (
            "Юпитер в Стрельце связывают с ростом через расширение горизонтов "
            "и обучение. Без обещаний удачи."
        ),
    },
    "saturn": {
        "capricorn": (
            "Сатурн в Козероге связывают с дисциплиной, ответственностью и "
            "долгой стратегией. Без образа «обречённости»."
        ),
    },
}


def requirements_for(report_type: str, brief: str) -> dict:
    min_words, max_words = WORD_LIMITS[report_type]
    return {
        "min_words": min_words,
        "max_words": max_words,
        "style_notes": [
            f"Тема раздела: {brief}.",
            "Минимум воды. Только наблюдения, связанные с фактами карты.",
        ],
        "avoid_repeating_sections": [],
    }


def focus_for(title: str) -> dict:
    return SECTION_CONTEXT_FOCUS.get(title, DEFAULT_SECTION_FOCUS)


def sorted_planets(planets: set[str] | frozenset[str]) -> list[str]:
    return [name for name in PLANET_ORDER if name in planets]


def filled_example(planet_ru: str, sign_ru: str, priority: int) -> dict | None:
    planet = PLANET_CODES[planet_ru]
    sign = SIGN_CODES[sign_ru]
    text = (FILLED_BLURBS.get(planet) or {}).get(sign)
    if not text:
        return None
    return {
        "id": f"{planet}_{sign}",
        "when": {"kind": "planet_sign", "planet": planet, "sign": sign},
        "text_ru": text,
        "priority": priority,
    }


def hint_cards_for(title: str) -> list[dict]:
    """Build placeholders only for indicators this section actually uses."""
    focus = focus_for(title)
    planets = sorted_planets(set(focus.get("planets") or ()))
    if not planets:
        planets = sorted_planets(set(DEFAULT_SECTION_FOCUS["planets"]))

    cards: list[dict] = []
    seen: set[str] = set()

    def add(card: dict) -> None:
        card_id = card["id"]
        if card_id in seen:
            return
        seen.add(card_id)
        cards.append(card)

    # Prefer three filled examples from planets that belong to this section.
    priority = 100
    for planet_ru in planets:
        planet = PLANET_CODES[planet_ru]
        for sign_code, text in (FILLED_BLURBS.get(planet) or {}).items():
            add(
                {
                    "id": f"{planet}_{sign_code}",
                    "when": {
                        "kind": "planet_sign",
                        "planet": planet,
                        "sign": sign_code,
                    },
                    "text_ru": text,
                    "priority": priority,
                }
            )
            priority -= 10
            if sum(1 for card in cards if card["text_ru"]) >= 3:
                break
        if sum(1 for card in cards if card["text_ru"]) >= 3:
            break

    # Full planet-in-sign grid for focus planets.
    for planet_ru in planets:
        planet = PLANET_CODES[planet_ru]
        for sign_ru in SIGN_ORDER:
            sign = SIGN_CODES[sign_ru]
            add(
                {
                    "id": f"{planet}_{sign}",
                    "when": {"kind": "planet_sign", "planet": planet, "sign": sign},
                    "text_ru": "",
                    "priority": 0,
                }
            )

    if focus.get("ascendant"):
        for sign_ru in SIGN_ORDER:
            sign = SIGN_CODES[sign_ru]
            add(
                {
                    "id": f"ascendant_{sign}",
                    "when": {"kind": "ascendant", "sign": sign},
                    "text_ru": "",
                    "priority": 0,
                }
            )

    houses = sorted(focus.get("houses") or ())
    if houses:
        for planet_ru in planets:
            planet = PLANET_CODES[planet_ru]
            for house in houses:
                add(
                    {
                        "id": f"{planet}_house_{house}",
                        "when": {
                            "kind": "planet_sign",
                            "planet": planet,
                            "house": house,
                        },
                        "text_ru": "",
                        "priority": 0,
                    }
                )

    aspect_mode = focus.get("aspects") or "involving"
    if aspect_mode != "none" and len(planets) >= 2:
        aspect_names = (
            ["квадрат", "оппозиция"]
            if aspect_mode == "hard"
            else ASPECT_ORDER
        )
        # Compact aspect matrix: consecutive pairs + first-to-rest, not full N².
        pairs = []
        for index, first in enumerate(planets):
            for second in planets[index + 1 :]:
                pairs.append((first, second))
        for first_ru, second_ru in pairs:
            first = PLANET_CODES[first_ru]
            second = PLANET_CODES[second_ru]
            for aspect_ru in aspect_names:
                aspect = ASPECT_CODES[aspect_ru]
                if (
                    not focus.get("synastry")
                    and ASPECT_ANGLES[aspect]
                    > MAX_SEPARATION.get(frozenset({first, second}), 180)
                ):
                    continue
                kind = "synastry_aspect" if focus.get("synastry") else "aspect"
                prefix = "synastry_" if focus.get("synastry") else "aspect_"
                add(
                    {
                        "id": f"{prefix}{first}_{aspect}_{second}",
                        "when": {
                            "kind": kind,
                            "first": first,
                            "second": second,
                            "aspect": aspect,
                        },
                        "text_ru": "",
                        "priority": 0,
                    }
                )

    # Guarantee at least three filled cards even for rare focus sets.
    filled = [card for card in cards if card["text_ru"]]
    if len(filled) < 3:
        for planet_ru in planets:
            for sign_ru in SIGN_ORDER:
                planet = PLANET_CODES[planet_ru]
                sign = SIGN_CODES[sign_ru]
                card_id = f"{planet}_{sign}"
                for card in cards:
                    if card["id"] == card_id and not card["text_ru"]:
                        card["text_ru"] = (
                            f"{planet_ru} в {sign_ru} традиционно читают в контексте "
                            f"темы «{title}»."
                        )
                        card["priority"] = 50
                        filled.append(card)
                        break
                if len(filled) >= 3:
                    break
            if len(filled) >= 3:
                break

    filled_ids = {card["id"] for card in cards if card["text_ru"]}
    ordered = [card for card in cards if card["id"] in filled_ids]
    ordered.extend(card for card in cards if card["id"] not in filled_ids)
    return ordered


def main() -> None:
    if HINTS_DIR.exists():
        for child in HINTS_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.name != "README.md":
                child.unlink()
    HINTS_DIR.mkdir(parents=True, exist_ok=True)

    index_sections = []
    for report_type, sections in SECTIONS.items():
        report_dir = HINTS_DIR / report_type
        report_dir.mkdir(parents=True, exist_ok=True)
        for number, (title, brief) in enumerate(sections, start=1):
            section_id = f"{report_type}.{number:02d}"
            filename = f"{number:02d}.json"
            cards = hint_cards_for(title)
            payload = {
                "schema_version": "section-hint.v1",
                "section_id": section_id,
                "report_type": report_type,
                "title_ru": title,
                "brief": brief,
                "prompt_requirements": requirements_for(report_type, brief),
                "hint_cards": cards,
            }
            (report_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            index_sections.append(
                {
                    "section_id": section_id,
                    "report_type": report_type,
                    "title_ru": title,
                    "path": f"{report_type}/{filename}",
                    "card_count": len(cards),
                }
            )

    (HINTS_DIR / "index.json").write_text(
        json.dumps(
            {"schema_version": "section-hints-index.v1", "sections": index_sections},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (HINTS_DIR / "README.md").write_text(
        "# Section hints\n\n"
        "Статические JSON-подсказки для генерации разделов.\n\n"
        "Набор `hint_cards` в каждом файле соответствует `SECTION_CONTEXT_FOCUS` "
        "этого раздела: планеты × знаки фокуса, при необходимости Асцендент, "
        "дома и аспекты/синастрия. Пустой `text_ru` — заготовка для ручного "
        "заполнения. Первые карточки с текстом — заполненные примеры.\n",
        encoding="utf-8",
    )
    samples = {
        item["title_ru"]: item["card_count"]
        for item in index_sections
        if item["title_ru"] in {
            "Твой портрет",
            "Твоё мышление",
            "Как ты влюбляешься",
            "Отношение к деньгам",
            "Общая динамика пары",
        }
    }
    print(f"Rebuilt {len(index_sections)} files. Sample sizes: {samples}")


if __name__ == "__main__":
    main()
