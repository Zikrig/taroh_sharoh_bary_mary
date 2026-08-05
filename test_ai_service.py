import unittest

from ai_service import _validate_content, build_prompt_payload
from reports import SECTIONS


def chart() -> dict:
    planets = {
        "Солнце": {"longitude": 10.0, "sign": "Овен", "degree": 10.0, "house": 1},
        "Луна": {"longitude": 70.0, "sign": "Близнецы", "degree": 10.0, "house": 3},
    }
    return {
        "date": "1990-01-01",
        "time": "12:00",
        "ascendant": {"longitude": 0.0, "sign": "Овен"},
        "houses": [index * 30.0 for index in range(12)],
        "planets": planets,
        "aspects": [],
    }


class AiServiceTests(unittest.TestCase):
    def test_one_payload_template_accepts_every_report_type(self):
        for report_type, sections in SECTIONS.items():
            payload = build_prompt_payload(report_type, chart(), chart() if report_type == "compatibility" else None)
            self.assertEqual(payload["report_type"], report_type)
            self.assertEqual([section["title"] for section in payload["sections"]], [title for title, _ in sections])

    def test_validates_expected_section_order(self):
        report_type = "money"
        content = {
            "title": "Отчёт",
            "intro": "Введение",
            "sections": [{"title": title, "content": "Текст"} for title, _ in SECTIONS[report_type]],
            "disclaimer": "Развлекательный материал.",
        }
        self.assertEqual(_validate_content(content, report_type), content)
        content["sections"].reverse()
        self.assertIsNone(_validate_content(content, report_type))


if __name__ == "__main__":
    unittest.main()
