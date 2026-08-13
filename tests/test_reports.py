import unittest
from pathlib import Path

from services.reports_new import (
    SECTIONS,
    _format_cover_date,
    _format_cover_time,
    _format_timezone_ru,
    generate_report,
)


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

    def test_cover_formats_date_time_and_russian_timezone(self):
        self.assertEqual(_format_cover_date("1998-07-15"), "15.07.1998")
        self.assertEqual(_format_cover_time("06:00"), "06:00")
        self.assertEqual(_format_cover_time("6:00:00"), "06:00")
        # Offset is taken for the birth date from the IANA zone.
        self.assertEqual(
            _format_timezone_ru("Asia/Novosibirsk", "1998-07-15"),
            "Новосибирск (UTC+7)",
        )
        moscow = _format_timezone_ru("Europe/Moscow", "2015-01-15")
        self.assertTrue(moscow.startswith("Москва (UTC"))
        self.assertIn("UTC+", moscow)


if __name__ == "__main__":
    unittest.main()
