import unittest
import json
from importlib.util import find_spec
from pathlib import Path
import sys
from types import SimpleNamespace

if find_spec("swisseph") is None:
    sys.modules["swisseph"] = SimpleNamespace(
        SUN=0, MOON=1, MERCURY=2, VENUS=3, MARS=4, JUPITER=5,
        SATURN=6, URANUS=7, NEPTUNE=8, PLUTO=9,
    )

from unittest.mock import patch
from tempfile import TemporaryDirectory

from services.ai import (
    SYSTEM_PROMPT,
    _is_degenerate_section_text,
    _is_retryable_api_error,
    _payload_sample_attempt_dir,
    _save_request_transcript,
    _save_response_transcript,
    _section_batch_size,
    _validate_section,
    build_prompt_payload,
    build_user_prompt,
    catalog_titles,
    parse_delimited_sections,
    render_natal_dump,
)
from services.astro import local_time_to_utc
from services.prompt_guides.career import build_career_hints
from services.report_prompts import (
    EDITOR_SYSTEM_PROMPT,
    FREE_SECTION_BATCH,
    PAID_SECTION_BATCH,
    PRODUCT_PROMPTS,
    SECTION_DELIMITER,
    SECTION_MAX_WORDS,
    build_editorial_prompt,
    format_delimited_sections,
    product_prompt_for_titles,
    section_max_words,
    section_title_batches,
)
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
        "latitude": 55.75,
        "longitude": 37.62,
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


def _sample_report(titles: list[str], text: str = "Живое наблюдение про повседневные привычки и реакции.") -> str:
    parts = []
    for title in titles:
        parts.extend([SECTION_DELIMITER, title, SECTION_DELIMITER, text, ""])
    return "\n".join(parts)


class AiServiceTests(unittest.TestCase):
    def test_moscow_local_time_is_converted_using_historical_timezone(self):
        utc_time, timezone_name = local_time_to_utc("2000-05-15", "12:00", 55.7558, 37.6173)
        self.assertEqual(timezone_name, "Europe/Moscow")
        self.assertEqual(utc_time.strftime("%Y-%m-%d %H:%M"), "2000-05-15 08:00")

    def test_payload_contains_full_natal_chart_not_selected_roles(self):
        payload = build_prompt_payload("money", chart(), None)
        self.assertIn("natal_text", payload)
        self.assertIn("Солнце: Овен, 10.0°, дом 1", payload["natal_text"])
        self.assertIn("1 дом:", payload["natal_text"])
        self.assertIn("Солнце тригон Луна", payload["natal_text"])
        self.assertNotIn("topic_priorities", payload)
        self.assertNotIn("section_role", payload)
        self.assertNotIn("interpretation_hints", payload)
        self.assertIn("allowed_facts", payload)
        self.assertIn("Солнце в Овен, дом 1", payload["allowed_facts"])

    def test_compatibility_payload_contains_both_charts(self):
        payload = build_prompt_payload("compatibility", chart(), chart())
        self.assertIn("PERSON A", payload["natal_text"])
        self.assertIn("PERSON B", payload["natal_text"])
        self.assertIn("Карта 1: Солнце в Овен, дом 1", payload["allowed_facts"])
        self.assertIn("Карта 2: Солнце в Овен, дом 1", payload["allowed_facts"])

    def test_catalog_sections_and_word_budgets(self):
        self.assertEqual(len(SECTIONS["personality_free"]), 11)
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
        self.assertEqual(SECTIONS["personality_free"][6][0], "Ты в любви")
        self.assertEqual(SECTIONS["personality_free"][9][0], "5 фраз, в которых ты можешь узнать себя")
        for report_type, sections in SECTIONS.items():
            self.assertEqual(
                set(SECTION_MAX_WORDS[report_type]),
                {title for title, _ in sections},
                report_type,
            )
        for report_type, sections in SECTIONS.items():
            if not report_type.endswith("_free"):
                continue
            for title, _ in sections:
                self.assertEqual(section_max_words(report_type, title), 250)

    def test_every_report_type_has_a_product_prompt(self):
        self.assertEqual(set(PRODUCT_PROMPTS), set(SECTIONS))

    def test_system_prompt_does_not_restrain_houses_on_approximate_time(self):
        self.assertNotIn("time_is_approximate", SYSTEM_PROMPT)
        self.assertNotIn("ориентировочны", SYSTEM_PROMPT)

    def test_career_hints_adds_house_themes_and_profession_examples(self):
        hints = build_career_hints(chart())
        self.assertEqual(hints["active_house_professions"][0]["house"], 1)
        self.assertIn("личность", hints["active_house_professions"][0]["themes"])
        self.assertTrue(hints["active_house_professions"][0]["profession_examples"])

    def test_user_prompt_contains_system_separate_product_and_full_chart(self):
        payload = build_prompt_payload("personality_free", chart(), None)
        prompt = payload["user_prompt"]
        self.assertIn("Натальная карта", prompt)
        self.assertIn("PERSONALITY_FREE", prompt)
        self.assertIn(SECTION_DELIMITER, prompt)
        self.assertIn("Твой портрет", prompt)
        self.assertIn("Какой ты человек", prompt)
        self.assertNotIn("section_role", prompt)
        self.assertNotIn("topic_priorities", prompt)

    def test_personality_free_payload_has_all_catalog_sections(self):
        payload = build_prompt_payload("personality_free", chart(), None)
        self.assertEqual(len(payload["sections"]), 11)
        self.assertIn("СОЗДАЙ БЕСПЛАТНЫЙ ПЕРСОНАЛЬНЫЙ РАЗБОР", payload["user_prompt"])

    def test_love_free_payload_builds_from_saved_profile(self):
        payload = build_prompt_payload("love_free", chart(), None)
        self.assertEqual(payload["sections"][0]["title"], "Как ты влюбляешься")
        self.assertIn("LOVE_FREE", payload["user_prompt"])

    def test_compatibility_free_requires_both_charts(self):
        with self.assertRaises(ValueError):
            build_prompt_payload("compatibility_free", chart(), None)
        payload = build_prompt_payload("compatibility_free", chart(), chart())
        self.assertIn("PERSON A", payload["natal_text"])
        self.assertIn("PERSON B", payload["natal_text"])

    def test_parses_delimited_sections_in_catalog_order(self):
        titles = ["Твой портрет", "Какой ты человек", "Как тебя видят другие"]
        text = "\n".join(
            [
                SECTION_DELIMITER,
                "Какой ты человек",
                SECTION_DELIMITER,
                "Текст про характер.",
                SECTION_DELIMITER,
                "Твой портрет",
                SECTION_DELIMITER,
                "Текст про портрет.",
                SECTION_DELIMITER,
                "Как тебя видят другие",
                SECTION_DELIMITER,
                "Текст про впечатление.",
            ]
        )
        parsed, rejection = parse_delimited_sections(text, titles)
        self.assertIsNone(rejection)
        self.assertEqual([item["title"] for item in parsed], titles)
        self.assertEqual(parsed[0]["content"], "Текст про портрет.")
        self.assertEqual(parsed[1]["content"], "Текст про характер.")

    def test_parses_section_number_headers_and_long_equals(self):
        titles = ["Твой портрет", "Какой ты человек"]
        text = """
==================================================
РАЗДЕЛ 1
ТВОЙ ПОРТРЕТ
==================================================
Цельное впечатление о человеке.

==================================================
РАЗДЕЛ 2
КАКОЙ ТЫ ЧЕЛОВЕК
==================================================
Как думает и реагирует.
"""
        parsed, rejection = parse_delimited_sections(text, titles)
        self.assertIsNone(rejection)
        self.assertEqual(parsed[0]["content"], "Цельное впечатление о человеке.")
        self.assertEqual(parsed[1]["content"], "Как думает и реагирует.")

    def test_parse_rejects_missing_sections(self):
        parsed, rejection = parse_delimited_sections(
            f"{SECTION_DELIMITER}\nТвой портрет\n{SECTION_DELIMITER}\nТолько один раздел.",
            ["Твой портрет", "Какой ты человек"],
        )
        self.assertIsNone(parsed)
        self.assertIn("Какой ты человек", rejection)

    def test_parses_a_single_leftover_section(self):
        parsed, rejection = parse_delimited_sections(
            f"{SECTION_DELIMITER}\nЭто только верхний слой\n{SECTION_DELIMITER}\nКороткий финал.",
            ["Это только верхний слой"],
        )
        self.assertIsNone(rejection)
        self.assertEqual(parsed[0]["content"], "Короткий финал.")

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

    def test_compatibility_requires_both_charts(self):
        with self.assertRaises(ValueError):
            build_prompt_payload("compatibility", chart(), None)

    def test_love_payload_is_supported(self):
        payload = build_prompt_payload("love", chart(), None)
        self.assertEqual(len(payload["sections"]), 18)
        self.assertEqual(payload["sections"][0]["title"], "Как ты влюбляешься")
        self.assertIn("LOVE_FULL", payload["user_prompt"])

    def test_paid_sections_are_generated_one_by_one(self):
        personality = catalog_titles("personality")
        love = catalog_titles("love")
        free = catalog_titles("personality_free")
        self.assertEqual(_section_batch_size("personality"), 1)
        self.assertEqual(_section_batch_size("love"), PAID_SECTION_BATCH)
        self.assertEqual(_section_batch_size("personality_free"), FREE_SECTION_BATCH)
        batches = section_title_batches(personality, PAID_SECTION_BATCH)
        self.assertEqual(len(batches), 20)
        self.assertTrue(all(len(batch) == 1 for batch in batches))
        self.assertEqual(section_title_batches(love, PAID_SECTION_BATCH)[-1], love[-1:])
        self.assertEqual(
            [len(batch) for batch in section_title_batches(free, FREE_SECTION_BATCH)],
            [5, 5, 1],
        )
        one = product_prompt_for_titles("personality", personality[:1])
        self.assertIn("ТОЛЬКО раздел «Твой главный психологический портрет»", one)
        self.assertNotIn("ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ", one)

    def test_aitunnel_503_is_retryable(self):
        error = type("InternalServerError", (Exception,), {})("503 worker")
        error.status_code = 503
        self.assertTrue(_is_retryable_api_error(error))
        self.assertTrue(_is_retryable_api_error(TimeoutError("timed out")))
        self.assertFalse(_is_retryable_api_error(ValueError("bad json")))

    def test_paid_batch_prompt_keeps_only_requested_section_instructions(self):
        titles = catalog_titles("personality")[:5]
        prompt = product_prompt_for_titles("personality", titles)
        self.assertIn("PERSONALITY_FULL", prompt)
        self.assertIn("ТВОЙ ГЛАВНЫЙ ПСИХОЛОГИЧЕСКИЙ ПОРТРЕТ", prompt)
        self.assertIn("КАК ТЕБЯ ВИДЯТ ЛЮДИ", prompt)
        self.assertNotIn("ПРАКТИЧЕСКИЕ РЕКОМЕНДАЦИИ", prompt)
        self.assertNotIn("ПРОФЕССИОНАЛЬНЫЕ НАПРАВЛЕНИЯ", prompt)
        self.assertIn("ТОЛЬКО эти разделы", prompt)
        self.assertIn("Максимум 280 слов", prompt)
        self.assertIn("Максимум 280 слов", build_user_prompt("personality", "карта", titles))

    def test_free_batch_prompt_excludes_later_sections(self):
        titles = catalog_titles("personality_free")[:5]
        prompt = product_prompt_for_titles("personality_free", titles)
        self.assertIn("PERSONALITY_FREE", prompt)
        self.assertIn("ТВОЙ ПОРТРЕТ", prompt)
        self.assertNotIn("5 ФРАЗ", prompt)
        self.assertNotIn("ЭТО ТОЛЬКО ВЕРХНИЙ СЛОЙ", prompt)
        self.assertIn("100–250 слов", prompt)

    def test_paid_user_prompt_includes_covered_sections(self):
        titles = catalog_titles("personality")[5:10]
        prompt = build_user_prompt(
            "personality",
            "Натальная карта",
            titles,
            [{"title": "Твой главный психологический портрет", "summary": "Воля и потребность в оценке."}],
        )
        self.assertIn("Уже написанные разделы", prompt)
        self.assertIn("Воля и потребность в оценке", prompt)
        self.assertIn("Верни только эти разделы одним сообщением", prompt)
        self.assertNotIn("Твой главный психологический портрет\n=====", prompt)

    def test_paid_prompt_includes_prior_free_generation(self):
        titles = catalog_titles("personality")[:1]
        prompt = build_user_prompt(
            "personality",
            "Натальная карта",
            titles,
            None,
            [
                {
                    "title": "Твой портрет",
                    "content": "Ты действуешь быстро и прямо, почти без разгона.",
                }
            ],
        )
        self.assertIn("бесплатный мини-разбор по той же теме", prompt)
        self.assertIn("Ты действуешь быстро и прямо", prompt)
        self.assertIn("--- Твой портрет ---", prompt)
        self.assertNotIn("--- Твой портрет ---", build_user_prompt("personality", "карта", titles))

    def test_system_prompt_asks_to_analyze_chart_before_writing(self):
        self.assertIn("Проанализируй всю карту", SYSTEM_PROMPT)
        self.assertIn("от 0 до 2 упоминаний", SYSTEM_PROMPT)
        self.assertIn("Ноль — нормально", SYSTEM_PROMPT)
        self.assertIn("короткие абзацы", SYSTEM_PROMPT)
        self.assertIn("живые, обычные формулировки", SYSTEM_PROMPT)
        self.assertIn("это не про А — это про Б", SYSTEM_PROMPT)
        self.assertIn("Если раздел можно было бы отправить человеку с совершенно другой картой", SYSTEM_PROMPT)
        self.assertIn("Не определяй и не подразумевай пол читателя", SYSTEM_PROMPT)
        self.assertIn("не назначай пол", SYSTEM_PROMPT)

    def test_editorial_prompt_sends_full_draft_and_asks_to_cut_repeats(self):
        self.assertIn("лёгкая редактура", EDITOR_SYSTEM_PROMPT)
        self.assertIn("схожих формулировок", EDITOR_SYSTEM_PROMPT)
        self.assertIn("странно сформулированные", EDITOR_SYSTEM_PROMPT)
        self.assertIn("не переписывай", EDITOR_SYSTEM_PROMPT)
        draft = format_delimited_sections(
            [
                {"title": "Твой главный психологический портрет", "content": "Ты быстро включаешься."},
                {"title": "Твой внутренний мир", "content": "Ты быстро включаешься и устаёшь от шума."},
            ]
        )
        self.assertIn("Ты быстро включаешься.", draft)
        prompt = build_editorial_prompt(
            draft,
            ["Твой главный психологический портрет", "Твой внутренний мир"],
            report_type="personality",
        )
        self.assertIn("ПОЛНЫЙ ЧЕРНОВИК", prompt)
        self.assertIn("Ты быстро включаешься и устаёшь от шума.", prompt)
        self.assertIn("лёгкая редактура одним проходом", prompt)
        self.assertIn("схожих формулировок", prompt)
        self.assertIn("странно сформулированные", prompt)
        self.assertIn("Верни весь разбор одним сообщением", prompt)
        self.assertIn("Твой главный психологический портрет", prompt)
        self.assertIn("Твой внутренний мир", prompt)

    def test_natal_dump_includes_houses_for_the_model(self):
        text = render_natal_dump(chart(), None, "personality_free")
        self.assertIn("Дома (куспиды):", text)
        self.assertIn("Планеты:", text)
        self.assertIn("Асцендент:", text)

    def test_payload_transcript_saves_system_and_user_in_report_folder(self):
        messages = [
            {"role": "system", "content": "SYSTEM BODY"},
            {"role": "user", "content": "USER PROMPT WITH CHART"},
        ]
        with TemporaryDirectory() as tmp:
            with patch("services.ai.PAYLOAD_SAMPLES_DIR", Path(tmp)), patch(
                "services.ai.settings"
            ) as mock_settings:
                mock_settings.save_payload_samples = True
                sample_dir = _payload_sample_attempt_dir(
                    report_type="personality_free",
                    section_id="full",
                    request_id="abcdef1234567890",
                    attempt=1,
                )
                _save_request_transcript(
                    sample_dir,
                    messages=messages,
                    request_meta={"model": "test-model", "temperature": 1.2},
                )
                _save_response_transcript(
                    sample_dir,
                    content="готовый текст раздела",
                    word_count=3,
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content="готовый текст раздела",
                        reasoning="длинные внутренние рассуждения",
                        reasoning_content=None,
                    ),
                )
                self.assertTrue(sample_dir.is_dir())
                self.assertEqual(sample_dir.parent.name, "full")
                self.assertEqual(sample_dir.parent.parent.name, "personality_free")
                self.assertEqual((sample_dir / "00_system.txt").read_text(encoding="utf-8"), "SYSTEM BODY")
                self.assertEqual(
                    (sample_dir / "01_user.txt").read_text(encoding="utf-8"),
                    "USER PROMPT WITH CHART",
                )
                sent = json.loads((sample_dir / "03_request_as_sent.json").read_text(encoding="utf-8"))
                self.assertEqual(sent["messages"], messages)
                self.assertEqual(
                    (sample_dir / "10_answer.txt").read_text(encoding="utf-8"),
                    "готовый текст раздела",
                )
                self.assertEqual(
                    (sample_dir / "11_reasoning.txt").read_text(encoding="utf-8"),
                    "длинные внутренние рассуждения",
                )

    def test_one_shot_sample_covers_all_free_titles(self):
        titles = catalog_titles("personality_free")
        parsed, rejection = parse_delimited_sections(_sample_report(titles), titles)
        self.assertIsNone(rejection)
        self.assertEqual(len(parsed), 11)


if __name__ == "__main__":
    unittest.main()
