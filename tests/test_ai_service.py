import unittest
from importlib.util import find_spec
import sys
from types import SimpleNamespace

if find_spec("swisseph") is None:
    sys.modules["swisseph"] = SimpleNamespace(
        SUN=0, MOON=1, MERCURY=2, VENUS=3, MARS=4, JUPITER=5,
        SATURN=6, URANUS=7, NEPTUNE=8, PLUTO=9,
    )

from services.ai import (
    SECTION_GUIDANCE,
    _allowed_facts,
    _section_batches,
    _validate_batch,
    build_batch_payload,
    build_prompt_payload,
)
from services.astro import local_time_to_utc, timezone_for_coordinates
from services.prompt_guides.career import build_career_hints
from services.reports import SECTIONS


def chart() -> dict:
    planets = {
        "Солнце": {"longitude": 10.0, "sign": "Овен", "degree": 10.0, "house": 1},
        "Луна": {"longitude": 70.0, "sign": "Близнецы", "degree": 10.0, "house": 3},
        "Венера": {"longitude": 100.0, "sign": "Рак", "degree": 10.0, "house": 4},
        "Уран": {"longitude": 200.0, "sign": "Весы", "degree": 20.0, "house": 7},
    }
    return {
        "date": "1990-01-01",
        "time": "12:00",
        "utc_time": "1990-01-01 09:00 UTC",
        "timezone": "Europe/Moscow",
        "time_is_approximate": False,
        "ascendant": {"longitude": 0.0, "sign": "Овен"},
        "houses": [index * 30.0 for index in range(12)],
        "planets": planets,
        "aspects": [
            {
                "first": "Солнце",
                "second": "Луна",
                "type": "тригон",
                "angle": 120,
                "orb": 1.2,
            },
            {
                "first": "Венера",
                "second": "Уран",
                "type": "квадрат",
                "angle": 90,
                "orb": 2.0,
            },
        ],
    }


class AiServiceTests(unittest.TestCase):
    def test_moscow_local_time_is_converted_using_historical_timezone(self):
        utc_time, timezone_name = local_time_to_utc("2000-05-15", "12:00", 55.7558, 37.6173)
        self.assertEqual(timezone_name, "Europe/Moscow")
        self.assertEqual(utc_time.strftime("%Y-%m-%d %H:%M"), "2000-05-15 08:00")

    def test_payload_contains_only_allowed_chart_facts(self):
        payload = build_prompt_payload("money", chart(), None)
        self.assertIn("allowed_facts", payload)
        # No "Карта 1:" for personal reports
        self.assertIn("Солнце в Овен, дом 1", payload["allowed_facts"])
        self.assertTrue(payload["sections"][1]["guidance"])

    def test_compatibility_payload_contains_labels(self):
        payload = build_prompt_payload("compatibility", chart(), chart())
        self.assertIn("allowed_facts", payload)
        self.assertIn("Карта 1: Солнце в Овен, дом 1", payload["allowed_facts"])
        self.assertIn("Карта 2: Солнце в Овен, дом 1", payload["allowed_facts"])

    def test_validates_section_batch_and_references(self):
        report_type = "money"
        allowed_facts = _allowed_facts(chart(), None, report_type)
        titles = [title for title, _ in SECTIONS[report_type][:3]]
        content = {
            "sections": [
                {
                    "title": titles[0],
                    "content": " ".join(["Точный"] * 30),
                    "references": [allowed_facts[0].upper() + "."],  # Test normalization
                },
                {
                    "title": titles[1],
                    "content": " ".join(["Точный"] * 30),
                    "references": [allowed_facts[1]],
                },
                {
                    "title": titles[2],
                    "content": " ".join(["Точный"] * 30),
                    "references": [allowed_facts[2]],
                }
            ],
        }
        validated = _validate_batch(content, titles, set(allowed_facts))
        self.assertIsNotNone(validated)
        self.assertEqual(validated[0]["references"][0], allowed_facts[0])

        content["sections"][0]["references"] = ["Выдуманный факт", allowed_facts[0]]
        self.assertIsNotNone(_validate_batch(content, titles, set(allowed_facts)))
        content["sections"][0]["references"] = ["Выдуманный факт"]
        self.assertIsNone(_validate_batch(content, titles, set(allowed_facts)))

    def test_splits_sections_into_three_item_batches(self):
        payload = build_prompt_payload("money", chart(), None)
        batches = _section_batches(payload["sections"])
        self.assertEqual([len(batch) for batch in batches], [3, 3, 3, 3, 1])

    def test_uses_embedded_sections_and_career_guidance(self):
        self.assertIn(
            ("Дом денег", "отношение к личным финансам, доходу и накоплениям"),
            SECTIONS["money"],
        )
        guidance = SECTION_GUIDANCE["personality"]["Карьера и призвание"]
        self.assertIn("2–4 конкретные роли", guidance)

    def test_career_hints_adds_house_themes_and_profession_examples(self):
        hints = build_career_hints(chart())
        self.assertEqual(hints["active_house_professions"][0]["house"], 1)
        self.assertIn("личность", hints["active_house_professions"][0]["themes"])
        self.assertTrue(hints["active_house_professions"][0]["profession_examples"])

    def test_batch_payload_filters_structured_chart_then_renders_facts(self):
        payload = build_prompt_payload("personality", chart(), None)
        batch = [
            section
            for section in payload["sections"]
            if section["title"] in {"Солнечный знак", "Лунный знак", "Введение"}
        ]
        trimmed = build_batch_payload(payload, batch)
        self.assertEqual(set(trimmed["primary_chart"]["planets"]), {"Солнце", "Луна"})
        self.assertNotIn("houses", trimmed["primary_chart"])
        self.assertNotIn("career_and_talent_hints", trimmed)
        # No "Карта 1:"
        self.assertIn("Солнце в Овен, дом 1", trimmed["allowed_facts"])
        self.assertIn("Луна в Близнецы, дом 3", trimmed["allowed_facts"])
        self.assertNotIn("Венера в Рак, дом 4", trimmed["allowed_facts"])
        self.assertIn(
            "Солнце тригон Луна",
            trimmed["allowed_facts"],
        )
        self.assertNotIn(
            "Венера квадрат Уран",
            trimmed["allowed_facts"],
        )


if __name__ == "__main__":
    unittest.main()
