import unittest

from handlers.router import NAMES, SCENARIO_INTROS, STUB_SCENARIOS, TEASER_TEXTS


class RouterUiTests(unittest.TestCase):
    def test_main_products_have_user_facing_names(self):
        self.assertEqual(NAMES["money"], "Деньги и реализация")
        self.assertEqual(STUB_SCENARIOS["love"], "❤️ Любовь и отношения")
        self.assertEqual(STUB_SCENARIOS["full"], "✨ Полный разбор")

    def test_current_scenarios_have_intro_and_static_preview(self):
        for scenario in ("personality", "compatibility", "money"):
            self.assertIn(scenario, SCENARIO_INTROS)
            self.assertIn(scenario, TEASER_TEXTS)
            self.assertIn("✨", TEASER_TEXTS[scenario])

    def test_static_preview_does_not_promise_generated_free_report(self):
        for text in TEASER_TEXTS.values():
            self.assertNotIn("генер", text.lower())


if __name__ == "__main__":
    unittest.main()
