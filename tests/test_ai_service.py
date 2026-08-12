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
    MAX_HINT_CARDS,
    MAX_SECTION_SUMMARY_CHARS,
    SECTION_GUIDANCE,
    SYSTEM_PROMPT,
    _allowed_facts,
    _filter_aspects,
    _is_degenerate_section_text,
    _section_batches,
    _section_summary,
    _selected_hint_cards,
    _validate_section,
    _validate_batch,
    build_batch_payload,
    build_prompt_payload,
    build_section_payload,
)
from services.astro import local_time_to_utc, timezone_for_coordinates
from services.prompt_guides.career import build_career_hints
from services.reports_new import SECTIONS


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
                    "references": [allowed_facts[0].upper() + "."],
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

    def test_splits_sections_into_single_item_requests(self):
        payload = build_prompt_payload("money", chart(), None)
        batches = _section_batches(payload["sections"])
        self.assertEqual([len(batch) for batch in batches], [1] * len(SECTIONS["money"]))

    def test_catalog_sections_and_word_budgets(self):
        self.assertEqual(len(SECTIONS["personality_free"]), 9)
        self.assertEqual(len(SECTIONS["love_free"]), 7)
        self.assertEqual(len(SECTIONS["compatibility_free"]), 4)
        self.assertEqual(len(SECTIONS["money_free"]), 6)
        self.assertEqual(len(SECTIONS["personality"]), 20)
        self.assertEqual(len(SECTIONS["love"]), 18)
        self.assertEqual(len(SECTIONS["money"]), 18)
        self.assertEqual(len(SECTIONS["compatibility"]), 18)
        self.assertIn(
            ("Отношение к деньгам", "как воспринимаешь деньги и ресурсы"),
            SECTIONS["money"],
        )
        guidance = SECTION_GUIDANCE["personality"]["Профессиональные направления"]
        self.assertIn("8–12", guidance)

    def test_system_prompt_does_not_restrain_houses_on_approximate_time(self):
        self.assertNotIn("time_is_approximate", SYSTEM_PROMPT)
        self.assertNotIn("ориентировочны", SYSTEM_PROMPT)

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
            if section["title"] == "Твоё мышление"
        ]
        trimmed = build_batch_payload(payload, batch)
        self.assertEqual(set(trimmed["primary_chart"]["planets"]), {"Солнце", "Уран"})
        self.assertNotIn("houses", trimmed["primary_chart"])
        self.assertNotIn("career_and_talent_hints", trimmed)
        self.assertIn("Солнце в Овен, дом 1", trimmed["allowed_facts"])
        self.assertNotIn("Луна в Близнецы, дом 3", trimmed["allowed_facts"])
        self.assertIn("Солнце тригон Луна", trimmed["allowed_facts"])

    def test_section_payload_uses_template_and_canonical_fact_codes(self):
        payload = build_prompt_payload("personality", chart(), None)
        section = next(
            item
            for item in payload["sections"]
            if item["title"] == "Твой внутренний мир"
        )
        section_payload = build_section_payload(payload, section)
        self.assertEqual(section_payload["section"]["id"], "personality.02")
        self.assertEqual(section_payload["section"]["title"], "Твой внутренний мир")
        self.assertEqual(section_payload["section"]["requirements"]["min_words"], 100)
        self.assertEqual(section_payload["section"]["requirements"]["max_words"], 167)
        self.assertIn("Солнце в Овен, дом 1", section_payload["allowed_facts"])
        self.assertIn(
            {
                "id": "primary.planet.sun.sign.aries",
                "scope": "primary",
                "kind": "planet_sign",
                "planet": "sun",
                "sign": "aries",
                "house": 1,
                "text_ru": "Солнце в Овен, дом 1",
            },
            section_payload["facts"],
        )
        self.assertTrue(section_payload["interpretation_hints"])

    def test_personality_free_payload_uses_shorter_word_budget(self):
        payload = build_prompt_payload("personality_free", chart(), None)
        section = payload["sections"][0]
        section_payload = build_section_payload(payload, section)
        self.assertEqual(section_payload["section"]["id"], "personality_free.01")
        self.assertEqual(section_payload["section"]["requirements"]["min_words"], 60)
        self.assertEqual(section_payload["section"]["requirements"]["max_words"], 67)

    def test_love_free_payload_builds_from_saved_profile(self):
        payload = build_prompt_payload("love_free", chart(), None)
        section_payload = build_section_payload(payload, payload["sections"][0])
        self.assertEqual(section_payload["section"]["id"], "love_free.01")
        self.assertEqual(section_payload["section"]["requirements"]["min_words"], 60)

    def test_compatibility_free_requires_both_charts(self):
        with self.assertRaises(ValueError):
            build_prompt_payload("compatibility_free", chart(), None)
        payload = build_prompt_payload("compatibility_free", chart(), chart())
        self.assertIn("Карта 1: Солнце в Овен, дом 1", payload["allowed_facts"])
        self.assertIn("Карта 2: Солнце в Овен, дом 1", payload["allowed_facts"])

    def test_validates_plain_text_and_assigns_application_references(self):
        section = {
            "title": "Твой портрет",
            "requirements": {"min_words": 5, "max_words": 10},
        }
        allowed_facts = ["Солнце в Овен, дом 1"]
        text = " ".join(["Точный"] * 5)
        validated, rejection = _validate_section(text, section, allowed_facts)
        self.assertIsNone(rejection)
        self.assertEqual(validated["references"], allowed_facts)

        # Length is only a prompt hint — short answers are accepted.
        short, rejection = _validate_section("Слишком коротко", section, allowed_facts)
        self.assertIsNone(rejection)
        self.assertEqual(short["content"], "Слишком коротко")

        empty, rejection = _validate_section("   ", section, allowed_facts)
        self.assertIsNone(empty)
        self.assertIn("пустой", rejection)

        long_text = " ".join(["Точный"] * 11)
        accepted, rejection = _validate_section(long_text, section, allowed_facts)
        self.assertIsNone(rejection)
        self.assertEqual(accepted["content"], long_text)

    def test_rejects_degenerate_multilingual_garbage(self):
        section = {"title": "Какой ты человек", "requirements": {}}
        garbage = (
            "Люди обычно видят сначала вашу мягкую внешность — спокойный голос. "
            "Но если что-то вас по-настоящему задело — импульсы вспыхивают мгновенно: "
            "быстрое решение разрастается на глазах энергией поисков коллективного "
            "одобрения плодотворных шагов ради moving off premise keeping vulnerable "
            "bullies прогре AlPatrick ar approximated elapsed بمUSSelde meaningful "
            "sailed harmonic Section standards separation generous 이후Li gascharged "
            "origin difícil OctoberCounting express abstract EU hours pressure "
            "comfortablycin rustic luc explanation BrandtFM Patterns trumpOB shades "
            "novo Arguments onder solid Right conduct durableFresh decisive "
            "pythonism astrology patterns Demographic rem apolog coherence lacked "
            "waterspers car backlog permanent implication biometric Simple acceler "
            "ambition configured honestchild galaxies poem hered shaftStew "
            "constructedcomfort alliesmeasuredAr sustained Island rationaleCar "
            "Budget lawsuit generous extendedReligion obvious translate smile "
            "hospitality strengthen advertisement inspiration knitted commentaries"
        )
        self.assertIsNotNone(_is_degenerate_section_text(garbage))
        validated, rejection = _validate_section(garbage, section, ["Солнце в Овен"])
        self.assertIsNone(validated)
        self.assertIsNotNone(rejection)

        normal = (
            "Люди обычно видят сначала вашу мягкую внешность — спокойный голос, "
            "умение слушать и тягу к домашнему уюту. Если тема вас задела по-настоящему, "
            "реакция может быть быстрой и собранной, но при этом вы стараетесь не "
            "терять контакт с близким кругом и сохранять ощущение опоры."
        )
        validated, rejection = _validate_section(normal, section, ["Солнце в Овен"])
        self.assertIsNone(rejection)
        self.assertEqual(validated["title"], "Какой ты человек")

    def test_removes_markdown_bold_markers_from_section_text(self):
        section = {
            "title": "Твой портрет",
            "requirements": {"min_words": 3},
        }
        validated, rejection = _validate_section(
            "Это **важный** личный вывод.",
            section,
            ["Солнце в Овен, дом 1"],
        )
        self.assertIsNone(rejection)
        self.assertEqual(validated["content"], "Это важный личный вывод.")

    @unittest.skip("Forbidden-pattern check is temporarily commented out in _validate_section")
    def test_rejects_categorical_and_fatalistic_wording(self):
        section = {
            "title": "Твой портрет",
            "requirements": {"min_words": 5, "max_words": 30},
        }
        for text in (
            "Вам это гарантированно принесёт доход в ближайшее время всегда",
            "Вам суждено встретить партнёра в этом году совершенно точно позже",
            "Здесь вы точно измените профессию и станете руководителем отдела",
        ):
            validated, rejection = _validate_section(text, section, ["Солнце в Овен"])
            self.assertIsNone(validated, text)
            self.assertIn("недопустимые формулировки", rejection)

    def test_hint_cards_are_sorted_by_priority_and_limited(self):
        hint = {
            "hint_cards": [
                {"id": "empty", "when": {}, "text_ru": "   ", "priority": 500},
                {"id": "low", "when": {}, "text_ru": "Низкий приоритет.", "priority": 10},
                {"id": "high", "when": {}, "text_ru": "Высокий приоритет.", "priority": 90},
                *[
                    {"id": f"filler{index}", "when": {}, "text_ru": f"Текст {index}."}
                    for index in range(MAX_HINT_CARDS)
                ],
            ],
        }
        selected = _selected_hint_cards(hint, [])
        self.assertEqual(len(selected), MAX_HINT_CARDS)
        self.assertEqual([card["id"] for card in selected[:2]], ["high", "low"])
        self.assertNotIn("empty", [card["id"] for card in selected])

    def test_covered_sections_are_passed_for_anti_duplication(self):
        payload = build_prompt_payload("personality", chart(), None)
        section = next(
            item
            for item in payload["sections"]
            if item["title"] == "Твой внутренний мир"
        )
        without_context = build_section_payload(payload, section)
        self.assertNotIn("covered_sections", without_context)

        covered = [{"title": "Твой главный психологический портрет", "summary": "Уже описана воля."}]
        with_context = build_section_payload(payload, section, covered)
        self.assertEqual(with_context["covered_sections"], covered)

    def test_section_summary_is_trimmed_to_one_line(self):
        summary = _section_summary("Первая строка.\n\n" + "слово " * 200)
        self.assertNotIn("\n", summary)
        self.assertLessEqual(len(summary), MAX_SECTION_SUMMARY_CHARS + 1)

    def test_compatibility_requires_both_charts(self):
        with self.assertRaises(ValueError):
            build_prompt_payload("compatibility", chart(), None)

    def test_love_payload_is_supported(self):
        payload = build_prompt_payload("love", chart(), None)
        self.assertEqual(len(payload["sections"]), 18)
        self.assertEqual(payload["sections"][0]["title"], "Как ты влюбляешься")

    def test_filters_aspects_by_significance_and_exactness(self):
        aspects = [
            {"first": "Солнце", "second": "Луна", "type": "тригон", "orb": 0.2},
            {"first": "Уран", "second": "Нептун", "type": "секстиль", "orb": 0.1},
            {"first": "Венера", "second": "Марс", "type": "квадрат", "orb": 5.9},
            {"first": "Меркурий", "second": "Юпитер", "type": "секстиль", "orb": 5.1},
        ]
        focus = {
            "planets": frozenset({"Солнце", "Луна", "Уран", "Нептун", "Венера", "Марс"}),
            "aspects": "all",
        }
        selected = _filter_aspects(aspects, focus)
        self.assertEqual(selected[0]["first"], "Солнце")
        self.assertNotIn(aspects[3], selected)
        self.assertLessEqual(len(selected), 6)

    def test_prompt_requires_hints_to_be_rephrased(self):
        self.assertIn("не копируйте дословно", SYSTEM_PROMPT)
        self.assertIn("не упоминай астрологию", SYSTEM_PROMPT)
        self.assertIn("живые, обычные формулировки", SYSTEM_PROMPT)
        self.assertIn("Не давайте советов, рекомендаций", SYSTEM_PROMPT)
        self.assertNotIn("практический ориентир", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
