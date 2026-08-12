"""Reduce maximum-word recommendations in every active section hint by one third."""
from __future__ import annotations

import json
from pathlib import Path

HINTS_DIR = Path(__file__).resolve().parent.parent / "section_hints"


def main() -> None:
    updated = 0
    for path in HINTS_DIR.glob("**/*.json"):
        if path.name == "index.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        requirements = data.get("prompt_requirements") or {}
        maximum = requirements.get("max_words")
        if not isinstance(maximum, int):
            continue
        requirements["max_words"] = round(maximum * 2 / 3)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        updated += 1
    print(f"Updated max_words in {updated} section hints.")


if __name__ == "__main__":
    main()
