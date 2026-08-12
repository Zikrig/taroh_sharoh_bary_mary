"""Fill every hint card in section_hints with concise astrological text."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HINTS_DIR = ROOT / "section_hints"

PLANETS = {
    "sun": ("Солнце", "воля и самовыражение"),
    "moon": ("Луна", "эмоции и чувство безопасности"),
    "mercury": ("Меркурий", "мышление и общение"),
    "venus": ("Венера", "ценности и близость"),
    "mars": ("Марс", "действие и энергия"),
    "jupiter": ("Юпитер", "рост и убеждения"),
    "saturn": ("Сатурн", "границы и ответственность"),
    "uranus": ("Уран", "свобода и обновление"),
    "neptune": ("Нептун", "воображение и эмпатия"),
    "pluto": ("Плутон", "интенсивность и изменения"),
}
SIGNS = {
    "aries": ("Овен", "инициативу и прямое действие"),
    "taurus": ("Телец", "устойчивость и практичность"),
    "gemini": ("Близнецы", "гибкость и обмен информацией"),
    "cancer": ("Рак", "эмоциональную близость и безопасность"),
    "leo": ("Лев", "самовыражение и признание"),
    "virgo": ("Дева", "анализ и внимание к деталям"),
    "libra": ("Весы", "гармонию и взаимодействие"),
    "scorpio": ("Скорпион", "глубину и собранность"),
    "sagittarius": ("Стрелец", "расширение горизонтов и поиск смысла"),
    "capricorn": ("Козерог", "дисциплину и долгосрочную цель"),
    "aquarius": ("Водолей", "самостоятельность и нестандартный взгляд"),
    "pisces": ("Рыбы", "чуткость и образное восприятие"),
}
ASPECTS = {
    "conjunction": "соединение усиливает общую тему",
    "sextile": "секстиль облегчает взаимодействие тем",
    "square": "квадрат создаёт напряжение между темами",
    "trine": "тригон поддерживает согласованное проявление тем",
    "opposition": "оппозиция ставит две темы в противовес",
}


def concise_text(condition: dict) -> str:
    kind = condition.get("kind")
    if kind == "planet_sign":
        planet, planet_theme = PLANETS[condition["planet"]]
        if "sign" in condition:
            sign, sign_theme = SIGNS[condition["sign"]]
            return f"{planet} в {sign}: {planet_theme} через {sign_theme}."
        if "house" in condition:
            return f"{planet} в {condition['house']}-м доме: {planet_theme} в сфере дома."
    if kind == "ascendant":
        sign, sign_theme = SIGNS[condition["sign"]]
        return f"Асцендент в {sign}: первое впечатление через {sign_theme}."
    if kind in {"aspect", "synastry_aspect"}:
        first = PLANETS[condition["first"]][0]
        second = PLANETS[condition["second"]][0]
        prefix = "Синастрия: " if kind == "synastry_aspect" else ""
        return f"{prefix}{first} — {second}: {ASPECTS[condition['aspect']]}."
    raise ValueError(f"Unsupported hint condition: {condition}")


def main() -> None:
    files = 0
    cards = 0
    for path in sorted(HINTS_DIR.glob("**/*.json")):
        if path.name == "index.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for card in data.get("hint_cards", []):
            text = concise_text(card.get("when") or {})
            if card.get("text_ru") != text:
                card["text_ru"] = text
                changed = True
            cards += 1
        if changed:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            files += 1
    print(f"Filled {cards} cards in {files} JSON files.")


if __name__ == "__main__":
    main()
