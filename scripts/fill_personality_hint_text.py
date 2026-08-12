"""Fill every existing personality hint card with a concise interpretation."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HINTS = ROOT / "section_hints" / "personality"

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
SIGNS = {
    "aries": ("Овен", "инициативу и прямое действие"),
    "taurus": ("Телец", "устойчивость и практичность"),
    "gemini": ("Близнецы", "гибкость и обмен информацией"),
    "cancer": ("Рак", "эмоциональную близость и безопасность"),
    "leo": ("Лев", "самовыражение и признание"),
    "virgo": ("Дева", "анализ и внимание к деталям"),
    "libra": ("Весы", "гармонию и взаимодействие"),
    "scorpio": ("Скорпион", "глубину и внутреннюю собранность"),
    "sagittarius": ("Стрелец", "расширение горизонтов и поиск смысла"),
    "capricorn": ("Козерог", "дисциплину и долгосрочную цель"),
    "aquarius": ("Водолей", "самостоятельность и нестандартный взгляд"),
    "pisces": ("Рыбы", "чуткость и образное восприятие"),
}
PLANET_THEMES = {
    "sun": "волю и самовыражение",
    "moon": "эмоции и чувство безопасности",
    "mercury": "мышление и общение",
    "venus": "ценности и близость",
    "mars": "действие и способ добиваться своего",
    "jupiter": "рост и убеждения",
    "saturn": "границы и ответственность",
    "uranus": "свободу и обновление",
    "neptune": "воображение и эмпатию",
    "pluto": "интенсивность и изменения",
}
ASPECTS = {
    "conjunction": "соединение усиливает общую тему",
    "sextile": "секстиль облегчает сотрудничество тем",
    "square": "квадрат создаёт напряжение между темами",
    "trine": "тригон поддерживает согласованное проявление тем",
    "opposition": "оппозиция ставит две темы в противовес",
}
PLANET_SHORT = {
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


def card_text(card: dict) -> str:
    condition = card.get("when") or {}
    kind = condition.get("kind")
    if kind == "planet_sign":
        planet = condition["planet"]
        if "sign" in condition:
            sign, expression = SIGNS[condition["sign"]]
            return (
                f"{PLANETS[planet]} в знаке {sign}: "
                f"{PLANET_THEMES[planet]} через {expression}."
            )
        if "house" in condition:
            house = condition["house"]
            return f"{PLANETS[planet]} в {house}-м доме: {PLANET_THEMES[planet]} в сфере дома."
    if kind == "ascendant":
        sign, expression = SIGNS[condition["sign"]]
        return f"Асцендент в {sign}: первое впечатление через {expression}."
    if kind in {"aspect", "synastry_aspect"}:
        first = PLANET_SHORT[condition["first"]]
        second = PLANET_SHORT[condition["second"]]
        return f"{first} — {second}: {ASPECTS[condition['aspect']]}."
    raise ValueError(f"Unsupported personality hint condition: {condition}")


def main() -> None:
    files = sorted(HINTS.glob("*.json"))
    updated_cards = 0
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for card in data.get("hint_cards", []):
            card["text_ru"] = card_text(card)
            updated_cards += 1
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"Filled {updated_cards} cards in {len(files)} personality files.")


if __name__ == "__main__":
    main()
