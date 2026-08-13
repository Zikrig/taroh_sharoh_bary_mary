import unittest
from importlib.util import find_spec
import sys
from types import SimpleNamespace

if find_spec("swisseph") is None:
    sys.modules["swisseph"] = SimpleNamespace(
        SUN=0, MOON=1, MERCURY=2, VENUS=3, MARS=4, JUPITER=5,
        SATURN=6, URANUS=7, NEPTUNE=8, PLUTO=9,
    )

from handlers.router import (
    FREE_REPORT_TYPES,
    FREE_UPSELL_TEXTS,
    NAMES,
    PAID_OFFER_TEXTS,
    PENDING_FREE_REPORTS,
    PENDING_FREE_REPORT_IDS_BY_USER,
    PRICES,
    SCENARIO_INTROS,
    admin_generations_menu,
    admin_menu,
    admin_text,
    free_section_keyboard,
    parse_free_section_callback,
    pdf_offer_keyboard,
    resolve_pending_free_report,
    store_pending_free_report,
)
from config.settings import settings


class RouterUiTests(unittest.TestCase):
    def setUp(self):
        PENDING_FREE_REPORTS.clear()
        PENDING_FREE_REPORT_IDS_BY_USER.clear()

    def test_main_products_have_user_facing_names_and_prices(self):
        self.assertEqual(NAMES["money"], "Деньги и реализация")
        self.assertEqual(NAMES["love"], "Любовь и отношения")
        self.assertEqual(set(PRICES), {"personality", "love", "money", "compatibility"})

    def test_current_scenarios_have_intro(self):
        for scenario in ("personality", "love", "compatibility", "money"):
            self.assertIn(scenario, SCENARIO_INTROS)
            self.assertNotIn("бесплатный", SCENARIO_INTROS[scenario].lower())

    def test_user_offer_requires_paid_pdf(self):
        self.assertEqual(set(PAID_OFFER_TEXTS), set(PRICES))
        for text in PAID_OFFER_TEXTS.values():
            self.assertIn("индивидуально", text)
        button = pdf_offer_keyboard("personality", admin_mode=False).inline_keyboard[0][0]
        self.assertIn("⭐", button.text)
        self.assertEqual(button.callback_data, "buy:personality")

    def test_all_scenarios_have_generated_free_reports(self):
        self.assertEqual(set(FREE_REPORT_TYPES), set(PRICES))
        for scenario, free_type in FREE_REPORT_TYPES.items():
            self.assertTrue(free_type.endswith("_free"))
            self.assertIn(scenario, FREE_UPSELL_TEXTS)

    def test_payload_samples_and_sampling_settings_are_configured(self):
        self.assertTrue(settings.save_payload_samples)
        self.assertGreaterEqual(settings.ai_temperature, 0.0)
        self.assertLessEqual(settings.ai_temperature, 2.0)
        self.assertGreater(settings.ai_presence_penalty, 0)
        self.assertGreater(settings.ai_frequency_penalty, 0)

    def test_free_section_button_contains_the_next_section_title(self):
        markup = free_section_keyboard("Ты в любви", "ab12cd34", 6)
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.text, "Посмотреть раздел «Ты в любви»")
        self.assertEqual(button.callback_data, "free_section:ab12cd34:6")

    def test_free_section_callback_keeps_report_and_index(self):
        self.assertEqual(
            parse_free_section_callback("free_section:ab12cd34:0"),
            ("ab12cd34", 0),
        )
        self.assertEqual(parse_free_section_callback("free_section:2"), (None, 2))
        self.assertIsNone(parse_free_section_callback("buy:personality"))

    def test_view_buttons_stay_bound_to_their_own_report(self):
        first_id = store_pending_free_report(
            7,
            "personality",
            [
                {"title": "Твой портрет", "content": "первый разбор"},
                {"title": "Какой ты человек", "content": "первый второй"},
            ],
        )
        second_id = store_pending_free_report(
            7,
            "love",
            [
                {"title": "Как ты влюбляешься", "content": "последний разбор"},
                {"title": "Близость", "content": "последний второй"},
                {"title": "Финал", "content": "последний третий"},
            ],
        )
        first = resolve_pending_free_report(7, first_id)
        second = resolve_pending_free_report(7, second_id)
        self.assertEqual(first["sections"][0]["content"], "первый разбор")
        self.assertEqual(second["sections"][0]["content"], "последний разбор")
        first_button = free_section_keyboard(
            first["sections"][0]["title"], first_id, 0
        ).inline_keyboard[0][0]
        self.assertEqual(first_button.callback_data, f"free_section:{first_id}:0")
        parsed = parse_free_section_callback(first_button.callback_data)
        bound = resolve_pending_free_report(7, parsed[0])
        self.assertEqual(bound["sections"][parsed[1]]["content"], "первый разбор")

    def test_free_daily_limit_admin_toggle_exists(self):
        markup = admin_menu(test_mode=False, free_daily_limit=True)
        texts = [button.text for row in markup.inline_keyboard for button in row]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("🟢 Лимит бесплатных: ВКЛ", texts)
        self.assertIn("admin:free_daily_limit_toggle", callbacks)
        text = admin_text(
            test_mode=False,
            free_daily_limit=True,
            balance_data={"balance": 12.5},
        )
        self.assertIn("Лимит бесплатных: ВКЛ", text)
        self.assertIn("не больше одного бесплатного мини-разбора в сутки", text)
        self.assertIn("admin:generations", callbacks)

    def test_admin_generations_menu_mirrors_products_without_stars(self):
        markup = admin_generations_menu()
        texts = [button.text for row in markup.inline_keyboard for button in row]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertEqual(
            texts[:4],
            [
                "🧠 Личность",
                "❤️ Любовь и отношения",
                "💰 Деньги и реализация",
                "💑 Совместимость",
            ],
        )
        self.assertEqual(
            callbacks[:4],
            [
                "admin_scenario:personality",
                "admin_scenario:love",
                "admin_scenario:money",
                "admin_scenario:compatibility",
            ],
        )
        paid = pdf_offer_keyboard("love", admin_mode=False).inline_keyboard[0][0]
        admin = pdf_offer_keyboard("love", admin_mode=True).inline_keyboard[0][0]
        self.assertIn("⭐", paid.text)
        self.assertEqual(paid.callback_data, "buy:love")
        self.assertNotIn("⭐", admin.text)
        self.assertEqual(admin.callback_data, "admin_buy:love")
        report_id = store_pending_free_report(
            1,
            "personality",
            [{"title": "Твой портрет", "content": "текст"}],
            admin_mode=True,
        )
        self.assertTrue(resolve_pending_free_report(1, report_id)["admin_mode"])


if __name__ == "__main__":
    unittest.main()
