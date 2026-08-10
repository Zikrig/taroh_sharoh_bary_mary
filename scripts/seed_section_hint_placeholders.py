"""Add empty hint-card placeholders for every condition used by a report section."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if "swisseph" not in sys.modules:
    sys.modules["swisseph"] = SimpleNamespace(
        SUN=0,
        MOON=1,
        MERCURY=2,
        VENUS=3,
        MARS=4,
        JUPITER=5,
        SATURN=6,
        URANUS=7,
        NEPTUNE=8,
        PLUTO=9,
    )

from services.ai import ASPECT_CODES, PLANET_CODES, SECTION_CONTEXT_FOCUS


ROOT = PROJECT_ROOT / "section_hints"
SIGNS = (
    "aries",
    "taurus",
    "gemini",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "scorpio",
    "sagittarius",
    "capricorn",
    "aquarius",
    "pisces",
)


def _card(card_id: str, condition: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card_id,
        "when": condition,
        "text_ru": "",
        "priority": 0,
    }


def _planet_placeholders(
    section_id: str,
    planets: set[str],
    houses: set[int],
) -> list[dict[str, Any]]:
    cards = []
    for planet_name in sorted(planets):
        planet = PLANET_CODES[planet_name]
        for sign in SIGNS:
            cards.append(_card(
                f"{section_id}.planet_sign.{planet}.{sign}",
                {"kind": "planet_sign", "planet": planet, "sign": sign},
            ))
        for house in sorted(houses):
            cards.append(_card(
                f"{section_id}.planet_house.{planet}.{house}",
                {"kind": "planet_sign", "planet": planet, "house": house},
            ))
    return cards


def _ascendant_placeholders(section_id: str) -> list[dict[str, Any]]:
    return [
        _card(
            f"{section_id}.ascendant.{sign}",
            {"kind": "ascendant", "sign": sign},
        )
        for sign in SIGNS
    ]


def _aspect_placeholders(
    section_id: str,
    planets: set[str],
    aspect_mode: str,
    *,
    synastry: bool,
) -> list[dict[str, Any]]:
    aspect_codes = (
        ("square", "opposition")
        if aspect_mode == "hard"
        else tuple(ASPECT_CODES.values())
    )
    kind = "synastry_aspect" if synastry else "aspect"
    cards = []
    for first_name in sorted(planets):
        for second_name in sorted(planets):
            if first_name == second_name:
                continue
            first = PLANET_CODES[first_name]
            second = PLANET_CODES[second_name]
            for aspect in aspect_codes:
                cards.append(_card(
                    f"{section_id}.{kind}.{first}.{aspect}.{second}",
                    {
                        "kind": kind,
                        "first": first,
                        "aspect": aspect,
                        "second": second,
                    },
                ))
    return cards


def placeholders_for(data: dict[str, Any]) -> list[dict[str, Any]]:
    focus = SECTION_CONTEXT_FOCUS[data["title_ru"]]
    planets = set(focus.get("planets") or ())
    houses = set(focus.get("houses") or ())
    cards = _planet_placeholders(data["section_id"], planets, houses)
    if focus.get("ascendant"):
        cards.extend(_ascendant_placeholders(data["section_id"]))
    aspect_mode = focus.get("aspects", "involving")
    if aspect_mode != "none":
        cards.extend(_aspect_placeholders(
            data["section_id"],
            planets,
            aspect_mode,
            synastry=bool(focus.get("synastry")),
        ))
    return cards


def main() -> None:
    added = 0
    for path in ROOT.glob("*/*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        cards = data.get("hint_cards") or []
        ids = {card.get("id") for card in cards}
        for card in placeholders_for(data):
            if card["id"] not in ids:
                cards.append(card)
                ids.add(card["id"])
                added += 1
        data["hint_cards"] = cards
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"added {added} empty hint cards")


if __name__ == "__main__":
    main()
