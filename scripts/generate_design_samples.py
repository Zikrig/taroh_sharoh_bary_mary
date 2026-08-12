from __future__ import annotations

import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.reports_new import SECTIONS, generate_report

OUTPUT_DIR = ROOT / "data" / "design_samples"
TEMP_REPORTS_DIR = ROOT / "reports"
SIGNS = (
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы",
)
PLANETS = (
    "Солнце", "Луна", "Меркурий", "Венера", "Марс",
    "Юпитер", "Сатурн", "Уран", "Нептун", "Плутон",
)
TEXT_FRAGMENTS = (
    "Это демонстрационный фрагмент текста для проверки композиции страницы.",
    "Здесь можно оценить длину строки, интервалы между блоками и читаемость.",
    "Смысл текста условный: он нужен только для работы над визуальным стилем.",
    "Такой абзац помогает проверить переносы, плотность набора и иерархию заголовков.",
    "В дальнейшем этот фрагмент будет заменён персональным анализом по карте.",
)


def demo_chart(rng: random.Random, date: str) -> dict:
    planets = {}
    for index, planet in enumerate(PLANETS):
        longitude = round((index * 31 + rng.uniform(0, 29)) % 360, 2)
        planets[planet] = {
            "longitude": longitude,
            "sign": SIGNS[int(longitude // 30)],
            "degree": round(longitude % 30, 1),
            "house": rng.randint(1, 12),
        }

    aspects = []
    for first, second, aspect_type in (
        ("Солнце", "Луна", "тригон"),
        ("Венера", "Марс", "секстиль"),
        ("Меркурий", "Сатурн", "квадрат"),
        ("Юпитер", "Нептун", "соединение"),
    ):
        aspects.append({
            "first": first,
            "second": second,
            "type": aspect_type,
            "angle": 120,
            "orb": round(rng.uniform(0.2, 5.8), 2),
        })

    return {
        "date": date,
        "time": "14:30",
        "utc_time": f"{date} 11:30 UTC",
        "timezone": "Europe/Moscow",
        "time_is_approximate": False,
        "latitude": 55.7558,
        "longitude": 37.6173,
        "planets": planets,
        "ascendant": {
            "longitude": 42.4,
            "sign": "Телец",
        },
        "houses": [round(index * 30, 2) for index in range(12)],
        "aspects": aspects,
    }


def random_text(rng: random.Random, words: int = 120) -> str:
    fragments = []
    while len(" ".join(fragments).split()) < words:
        fragments.append(rng.choice(TEXT_FRAGMENTS))
    return " ".join(fragments)


def demo_content(report_type: str, rng: random.Random) -> dict:
    references = [
        "Карта 1: Солнце в Телец, дом 2",
        "Карта 1: Луна в Весы, дом 7",
    ]
    return {
        "title": f"Демонстрационный отчёт — {report_type}",
        "intro": random_text(rng, 90),
        "sections": [
            {
                "title": title,
                "content": random_text(rng),
                "references": references,
            }
            for title, _ in SECTIONS[report_type]
        ],
        "disclaimer": (
            "Демонстрационный текст создан случайно для проверки дизайна PDF. "
            "Он не является астрологическим анализом."
        ),
    }


def main() -> None:
    rng = random.Random()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    for report_type in ("personality", "compatibility", "money"):
        primary = demo_chart(rng, "2000-05-15")
        partner = demo_chart(rng, "1998-09-21") if report_type == "compatibility" else None
        generated_path = generate_report(
            report_type,
            primary,
            partner,
            demo_content(report_type, rng),
            recipient_name="Демо-пользователь",
            recipient_username="design_preview",
        )
        target = OUTPUT_DIR / f"sample_{report_type}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        shutil.move(generated_path, target)
        print(target.relative_to(ROOT))


if __name__ == "__main__":
    main()
