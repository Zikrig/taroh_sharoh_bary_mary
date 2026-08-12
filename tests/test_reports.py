import unittest
from pathlib import Path

from services.reports_new import SECTIONS, generate_report


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


def content() -> dict:
    facts = ["Карта 1: Солнце в Овен, дом 1", "Карта 1: Луна в Близнецы, дом 3"]
    return {
        "title": "Точный отчёт",
        "intro": "Введение в рассчитанную карту.",
        "sections": [
            {"title": title, "content": "Текст раздела.", "references": facts}
            for title, _ in SECTIONS["money"]
        ],
        "disclaimer": "Материал для саморефлексии.",
    }


class ReportTests(unittest.TestCase):
    def test_pdf_has_a_vector_chart_and_tables(self):
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        report_path = generate_report("money", chart(), None, content(), "Fedor", "fgriz")
        self.assertTrue(report_path.exists())
        self.assertGreater(report_path.stat().st_size, 1_000)
        report_path.unlink()

    def test_report_rejects_missing_ai_content(self):
        with self.assertRaises(ValueError):
            generate_report("money", chart(), None, None)


if __name__ == "__main__":
    unittest.main()
