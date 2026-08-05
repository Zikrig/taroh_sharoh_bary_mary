import unittest
from importlib.util import find_spec
import sys
from types import SimpleNamespace

if find_spec("swisseph") is None:
    sys.modules["swisseph"] = SimpleNamespace(
        SUN=0, MOON=1, MERCURY=2, VENUS=3, MARS=4, JUPITER=5,
        SATURN=6, URANUS=7, NEPTUNE=8, PLUTO=9,
    )

from services.ai import _allowed_facts, _validate_content, build_prompt_payload
from services.astro import local_time_to_utc, timezone_for_coordinates
from services.reports import SECTIONS


def chart() -> dict:
    planets = {
        "Солнце": {"longitude": 10.0, "sign": "Овен", "degree": 10.0, "house": 1},
        "Луна": {"longitude": 70.0, "sign": "Близнецы", "degree": 10.0, "house": 3},
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
        "aspects": [],
    }


class AiServiceTests(unittest.TestCase):
    def test_moscow_local_time_is_converted_using_historical_timezone(self):
        utc_time, timezone_name = local_time_to_utc("2000-05-15", "12:00", 55.7558, 37.6173)
        self.assertEqual(timezone_name, "Europe/Moscow")
        self.assertEqual(utc_time.strftime("%Y-%m-%d %H:%M"), "2000-05-15 08:00")

    def test_payload_contains_only_allowed_chart_facts(self):
        payload = build_prompt_payload("money", chart(), None)
        self.assertIn("allowed_facts", payload)
        self.assertIn("Карта 1: Солнце в Овен, дом 1", payload["allowed_facts"])

    def test_validates_expected_section_order_and_references(self):
        report_type = "money"
        allowed_facts = _allowed_facts(chart(), None)
        content = {
            "title": "Отчёт",
            "intro": "Введение",
            "sections": [
                {
                    "title": title,
                    "content": " ".join(["Точный"] * 100),
                    "references": allowed_facts[:2],
                }
                for title, _ in SECTIONS[report_type]
            ],
            "disclaimer": "Развлекательный материал.",
        }
        self.assertEqual(_validate_content(content, report_type, set(allowed_facts)), content)
        content["sections"][0]["references"] = ["Выдуманный факт", allowed_facts[0]]
        self.assertIsNone(_validate_content(content, report_type, set(allowed_facts)))


if __name__ == "__main__":
    unittest.main()
