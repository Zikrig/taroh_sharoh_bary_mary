"""Remove natal aspect cards that planetary elongations make impossible."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HINTS_DIR = ROOT / "section_hints"

PLANET_CODES = {
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
}
ASPECT_ANGLES = {
    "conjunction": 0,
    "sextile": 60,
    "square": 90,
    "trine": 120,
    "opposition": 180,
}

# Maximum geocentric separation imposed by solar elongation.
MAX_SEPARATION = {
    frozenset({"sun", "mercury"}): 28,
    frozenset({"sun", "venus"}): 48,
    frozenset({"mercury", "venus"}): 76,
}


def is_impossible(card: dict) -> bool:
    condition = card.get("when") or {}
    if condition.get("kind") != "aspect":
        return False
    first = condition.get("first")
    second = condition.get("second")
    aspect = condition.get("aspect")
    if first not in PLANET_CODES or second not in PLANET_CODES:
        return False
    maximum = MAX_SEPARATION.get(frozenset({first, second}))
    return maximum is not None and ASPECT_ANGLES.get(aspect, 0) > maximum


def main() -> None:
    removed = 0
    files = 0
    for path in sorted(HINTS_DIR.glob("**/*.json")):
        if path.name == "index.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        cards = data.get("hint_cards")
        if not isinstance(cards, list):
            continue
        filtered = [card for card in cards if not is_impossible(card)]
        removed += len(cards) - len(filtered)
        if len(filtered) != len(cards):
            data["hint_cards"] = filtered
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            files += 1
    print(f"Removed {removed} impossible natal aspect cards from {files} files.")


if __name__ == "__main__":
    main()
