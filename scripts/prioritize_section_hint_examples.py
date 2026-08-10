"""Keep three filled example cards at the beginning of every hint JSON file."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent / "section_hints"
PLANETS = {
    "sun": "Солнце",
    "moon": "Луна",
    "mercury": "Меркурий",
    "venus": "Венера",
    "mars": "Марс",
    "jupiter": "Юпитер",
    "saturn": "Сатурн",
    "uranus": "Уран",
    "neptune": "Нептун",
    "pluto": "Плутон",
}
PLANET_GENITIVE = {
    "sun": "Солнца",
    "moon": "Луны",
    "mercury": "Меркурия",
    "venus": "Венеры",
    "mars": "Марса",
    "jupiter": "Юпитера",
    "saturn": "Сатурна",
    "uranus": "Урана",
    "neptune": "Нептуна",
    "pluto": "Плутона",
}
SIGNS = {
    "aries": "Овне",
    "taurus": "Тельце",
    "gemini": "Близнецах",
    "cancer": "Раке",
    "leo": "Льве",
    "virgo": "Деве",
    "libra": "Весах",
    "scorpio": "Скорпионе",
    "sagittarius": "Стрельце",
    "capricorn": "Козероге",
    "aquarius": "Водолее",
    "pisces": "Рыбах",
}
ASPECTS = {
    "conjunction": "соединение",
    "sextile": "секстиль",
    "square": "квадрат",
    "trine": "тригон",
    "opposition": "оппозиция",
}


def example_text(card: dict) -> str:
    condition = card["when"]
    kind = condition["kind"]
    if kind == "planet_sign":
        if "sign" in condition:
            return (
                f"Положение {PLANET_GENITIVE[condition['planet']]} в {SIGNS[condition['sign']]} "
                "традиционно интерпретируют "
                "в контексте темы раздела и остальных показателей карты."
            )
        return (
            f"Положение {PLANET_GENITIVE[condition['planet']]} в {condition['house']}-м доме "
            "связывают с темой этой сферы "
            "жизни; вывод требует сопоставления с другими показателями карты."
        )
    if kind == "ascendant":
        return (
            f"Асцендент в {SIGNS[condition['sign']]} описывает первое впечатление "
            "и способ проявляться вовне только при известном времени рождения."
        )
    first = PLANETS[condition["first"]]
    second = PLANETS[condition["second"]]
    aspect = ASPECTS[condition["aspect"]]
    prefix = "В синастрии " if kind == "synastry_aspect" else ""
    return (
        f"{prefix}{aspect} {first} и {second} показывает связь этих тем; "
        "её следует интерпретировать вместе с остальными фактами."
    )


def main() -> None:
    updated = 0
    for path in ROOT.glob("*/*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        cards = data.get("hint_cards") or []
        filled = [
            card for card in cards
            if isinstance(card.get("text_ru"), str) and card["text_ru"].strip()
        ]
        filled_count_before = len(filled)
        changed = False
        for card in filled:
            text = card["text_ru"]
            if "традиционно интерпретируют в контексте темы раздела" in text:
                card["text_ru"] = example_text(card)
                changed = True
        if len(filled) < 3:
            for card in cards:
                if card in filled:
                    continue
                card["text_ru"] = example_text(card)
                filled.append(card)
                if len(filled) == 3:
                    break
        if len(filled) < 3:
            raise ValueError(f"{path}: недостаточно карточек для трёх примеров.")
        empty = [card for card in cards if card not in filled]
        reordered = filled + empty
        if reordered != cards or filled_count_before != len(filled) or changed:
            data["hint_cards"] = reordered
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            updated += 1
    print(f"prioritized examples in {updated} section files")


if __name__ == "__main__":
    main()
