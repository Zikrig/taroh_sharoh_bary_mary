"""Remove generated meta-prefixes from section hint text."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent / "section_hints"
PREFIX = re.compile(r"^Для раздела «[^»]+»\s*")
SUFFIX = (
    " Используй вероятностную формулировку и не делай из одного показателя "
    "окончательный вывод о человеке."
)


def main() -> None:
    updated = 0
    for path in ROOT.glob("*/*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for card in data.get("hint_cards") or []:
            text = card.get("text_ru")
            if not isinstance(text, str):
                continue
            cleaned = PREFIX.sub("", text).removesuffix(SUFFIX)
            if cleaned != text:
                card["text_ru"] = cleaned
                changed = True
        if changed:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            updated += 1
    print(f"cleaned {updated} section files")


if __name__ == "__main__":
    main()
