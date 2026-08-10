import unittest

from handlers.router import NAMES, PRICES, SCENARIO_INTROS, TEASER_TEXTS
from config.settings import settings


class RouterUiTests(unittest.TestCase):
    def test_main_products_have_user_facing_names_and_prices(self):
        self.assertEqual(NAMES["money"], "Деньги и реализация")
        self.assertEqual(NAMES["love"], "Любовь и отношения")
        self.assertEqual(set(PRICES), {"personality", "love", "money", "compatibility"})

    def test_current_scenarios_have_intro(self):
        for scenario in ("personality", "love", "compatibility", "money"):
            self.assertIn(scenario, SCENARIO_INTROS)

    def test_paid_previews_exist_except_personality_uses_generated_free(self):
        self.assertNotIn("personality", TEASER_TEXTS)
        for scenario in ("love", "money", "compatibility"):
            self.assertIn(scenario, TEASER_TEXTS)
            self.assertIn("✨", TEASER_TEXTS[scenario])

    def test_payload_samples_are_disabled_by_default(self):
        self.assertFalse(settings.save_payload_samples)


if __name__ == "__main__":
    unittest.main()
