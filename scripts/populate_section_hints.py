"""Fill empty section-hint JSON files with theory-based examples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent / "section_hints"

PERSONALITY_EXAMPLES = [
    (
        "sun_aries",
        {"kind": "planet_sign", "planet": "sun", "sign": "aries"},
        "Солнце в Овне может усиливать инициативу, самостоятельность и готовность начинать новое.",
    ),
    (
        "moon_cancer",
        {"kind": "planet_sign", "planet": "moon", "sign": "cancer"},
        "Луна в Раке может усиливать чувствительность к атмосфере и потребность в эмоциональной безопасности.",
    ),
    (
        "sun_moon_trine",
        {"kind": "aspect", "first": "sun", "aspect": "trine", "second": "moon"},
        "Гармоничная связь Солнца и Луны может помогать согласовывать волю и эмоциональные потребности.",
    ),
]

MONEY_EXAMPLES = [
    (
        "venus_taurus",
        {"kind": "planet_sign", "planet": "venus", "sign": "taurus"},
        "Венера в Тельце может связывать ресурс с качеством, устойчивостью и постепенным созданием материальной опоры.",
    ),
    (
        "jupiter_sagittarius",
        {"kind": "planet_sign", "planet": "jupiter", "sign": "sagittarius"},
        "Юпитер в Стрельце может поддерживать рост через обучение, расширение связей и профессионального горизонта.",
    ),
    (
        "saturn_capricorn",
        {"kind": "planet_sign", "planet": "saturn", "sign": "capricorn"},
        "Сатурн в Козероге подчёркивает пользу системы, сроков и последовательных действий; он не обещает конкретного дохода.",
    ),
]

COMPATIBILITY_EXAMPLES = [
    (
        "moon_cancer",
        {"kind": "planet_sign", "planet": "moon", "sign": "cancer"},
        "Луна в Раке может усиливать потребность в тепле, предсказуемости и эмоциональном отклике.",
    ),
    (
        "venus_libra",
        {"kind": "planet_sign", "planet": "venus", "sign": "libra"},
        "Венера в Весах может связывать проявление симпатии с взаимностью, тактом и честным диалогом.",
    ),
    (
        "moon_trine_moon",
        {"kind": "synastry_aspect", "first": "moon", "aspect": "trine", "second": "moon"},
        "Гармоничная связь Лун может облегчать эмоциональный отклик, но не отменяет необходимости проговаривать потребности.",
    ),
]


def examples_for(report_type: str) -> list[tuple[str, dict[str, str], str]]:
    if report_type == "money":
        return MONEY_EXAMPLES
    if report_type == "compatibility":
        return COMPATIBILITY_EXAMPLES
    return PERSONALITY_EXAMPLES


def make_cards(data: dict[str, Any]) -> list[dict[str, Any]]:
    cards = data.get("hint_cards") or []
    existing_ids = {card.get("id") for card in cards}
    for card_id, condition, text in examples_for(data["report_type"]):
        if len(cards) >= 3:
            break
        full_id = f"{data['section_id']}.{card_id}"
        if full_id in existing_ids:
            continue
        cards.append({
            "id": full_id,
            "when": condition,
            "text_ru": text,
            "priority": 50 - len(cards),
        })
    return cards


def main() -> None:
    updated = 0
    for path in ROOT.glob("*/*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if len(data.get("hint_cards") or []) >= 3:
            continue
        data["hint_cards"] = make_cards(data)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        updated += 1
    print(f"updated {updated} section files")


if __name__ == "__main__":
    main()
