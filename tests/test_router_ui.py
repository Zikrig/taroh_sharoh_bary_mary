import unittest

from handlers.router import (
    FREE_REPORT_TYPES,
    FREE_UPSELL_TEXTS,
    NAMES,
    PRICES,
    SCENARIO_INTROS,
    free_section_keyboard,
)
from config.settings import settings


class RouterUiTests(unittest.TestCase):
    def test_main_products_have_user_facing_names_and_prices(self):
        self.assertEqual(NAMES["money"], "Деньги и реализация")
        self.assertEqual(NAMES["love"], "Любовь и отношения")
        self.assertEqual(set(PRICES), {"personality", "love", "money", "compatibility"})

    def test_current_scenarios_have_intro(self):
        for scenario in ("personality", "love", "compatibility", "money"):
            self.assertIn(scenario, SCENARIO_INTROS)

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
        markup = free_section_keyboard("Ты в любви", 6)
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.text, "Посмотреть раздел «Ты в любви»")
        self.assertEqual(button.callback_data, "free_section:6")


if __name__ == "__main__":
    unittest.main()
