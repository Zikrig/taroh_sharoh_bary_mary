"""Add love_free, compatibility_free and money_free section hints from full-report templates."""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HINTS_DIR = PROJECT_ROOT / "section_hints"
INDEX_PATH = HINTS_DIR / "index.json"

FREE_SECTION_SOURCES: dict[str, list[tuple[str, str]]] = {
    "love_free": [
        ("love/01.json", "как возникает влюблённость"),
        ("love/02.json", "что цепляет в другом человеке"),
        ("love/03.json", "потребности и ощущение безопасности"),
        ("love/09.json", "стиль спора и восстановления контакта"),
        ("love/14.json", "характер и стиль партнёра, не только знаки"),
        ("love/17.json", "риски и зоны внимания"),
        ("love/18.json", "сводка любовного профиля"),
    ],
    "compatibility_free": [
        ("compatibility/02.json", "чувства, поддержка и отклик"),
        ("compatibility/03.json", "химия и интерес друг к другу"),
        ("compatibility/14.json", "зоны напряжения и роста"),
        ("compatibility/01.json", "как вы взаимодействуете в целом"),
    ],
    "money_free": [
        ("money/01.json", "как воспринимаешь деньги и ресурсы"),
        ("money/02.json", "драйверы дохода"),
        ("money/04.json", "готовность к неопределённости"),
        ("money/14.json", "конкретные сферы и роли"),
        ("money/08.json", "привычки и установки"),
        ("money/17.json", "одно ключевое направление развития"),
    ],
}


def clone_free_hint(source_rel: str, report_type: str, number: int, brief: str) -> dict:
    source = json.loads((HINTS_DIR / source_rel).read_text(encoding="utf-8"))
    return {
        "schema_version": "section-hint.v1",
        "section_id": f"{report_type}.{number:02d}",
        "report_type": report_type,
        "title_ru": source["title_ru"],
        "brief": brief,
        "prompt_requirements": {
            "min_words": 60,
            "max_words": 67,
            "style_notes": [
                f"Тема раздела: {brief}.",
                "Минимум воды. Только конкретные наблюдения.",
            ],
            "avoid_repeating_sections": [],
        },
        "hint_cards": source["hint_cards"],
    }


def main() -> None:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    existing_types = {item["report_type"] for item in index["sections"]}
    new_entries: list[dict] = []

    for report_type, sources in FREE_SECTION_SOURCES.items():
        if report_type in existing_types:
            print(f"Skip {report_type}: already in index")
            continue
        report_dir = HINTS_DIR / report_type
        report_dir.mkdir(parents=True, exist_ok=True)
        for number, (source_rel, brief) in enumerate(sources, start=1):
            payload = clone_free_hint(source_rel, report_type, number, brief)
            filename = f"{number:02d}.json"
            (report_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            new_entries.append(
                {
                    "section_id": payload["section_id"],
                    "report_type": report_type,
                    "title_ru": payload["title_ru"],
                    "path": f"{report_type}/{filename}",
                    "card_count": len(payload["hint_cards"]),
                }
            )
            print(f"Wrote {report_type}/{filename}")

    if not new_entries:
        print("Nothing to add.")
        return

    # Keep personality_free first, then other free types, then paid products.
    free_order = ("personality_free", "love_free", "compatibility_free", "money_free")
    paid = [item for item in index["sections"] if not item["report_type"].endswith("_free")]
    free_existing = [
        item for item in index["sections"] if item["report_type"].endswith("_free")
    ]
    free_by_type: dict[str, list[dict]] = {}
    for item in free_existing + new_entries:
        free_by_type.setdefault(item["report_type"], []).append(item)
    index["sections"] = [
        section
        for report_type in free_order
        for section in free_by_type.get(report_type, [])
    ] + paid
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Added {len(new_entries)} sections to index.json")


if __name__ == "__main__":
    main()
