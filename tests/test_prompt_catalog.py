import unittest
from importlib.util import find_spec
import sys
from types import SimpleNamespace

if find_spec("swisseph") is None:
    sys.modules["swisseph"] = SimpleNamespace(
        SUN=0, MOON=1, MERCURY=2, VENUS=3, MARS=4, JUPITER=5,
        SATURN=6, URANUS=7, NEPTUNE=8, PLUTO=9,
    )

from handlers.admin_prompts import (
    edit_keyboard,
    products_menu,
    prompts_root_menu,
)
from services.prompt_catalog import (
    REPORT_TYPE_ORDER,
    all_prompt_keys,
    default_prompt_text,
    is_known_prompt_key,
    missing_placeholders,
    parent_callback,
    product_section_nodes,
)
from services.report_prompts import (
    PIPELINE_TEMPLATES,
    PRODUCT_PROMPTS,
    SYSTEM_PROMPT,
    apply_prompt_overrides,
    assembled_product_prompt,
    default_product_parts,
    product_prompt_for_titles,
    product_prompt_parts,
)
from services.reports_new import SECTIONS


class PromptCatalogTests(unittest.TestCase):
    def tearDown(self):
        apply_prompt_overrides(None)

    def test_catalog_covers_every_product_block(self):
        keys = all_prompt_keys()
        self.assertIn("sys", keys)
        self.assertIn("ed", keys)
        for name in PIPELINE_TEMPLATES:
            self.assertIn(f"p.{name}", keys)
        self.assertEqual(set(REPORT_TYPE_ORDER), set(PRODUCT_PROMPTS))
        for report_type in REPORT_TYPE_ORDER:
            self.assertIn(f"i.{report_type}", keys)
            _intro, blocks = default_product_parts(report_type)
            self.assertEqual(len(product_section_nodes(report_type)), len(blocks))
            self.assertEqual(len(blocks), len(SECTIONS[report_type]), report_type)
            for index in range(len(blocks)):
                self.assertIn(f"s.{report_type}.{index}", keys)

    def test_callback_data_stays_within_telegram_limit(self):
        for key in all_prompt_keys():
            for prefix in ("admin:predit:", "admin:prreset:", "admin:prfile:"):
                self.assertLessEqual(len(prefix + key), 64, prefix + key)

    def test_override_changes_only_the_chosen_section(self):
        title = "Какой партнёр тебе подходит"
        _intro, blocks = default_product_parts("compatibility")
        index = next(
            i for i, (header, _body) in enumerate(blocks)
            if title.casefold() in header.casefold()
        )
        apply_prompt_overrides(
            {f"s.compatibility.{index}": "Где возможна встреча. Только тест."}
        )
        prompt = product_prompt_for_titles("compatibility", [title])
        self.assertIn("Где возможна встреча. Только тест.", prompt)
        self.assertNotIn("Где возможна встреча. Только тест.", PRODUCT_PROMPTS["compatibility"])
        love = product_prompt_for_titles("love", ["Какой партнёр тебе подходит"])
        self.assertNotIn("Где возможна встреча. Только тест.", love)

    def test_pipeline_placeholder_check(self):
        self.assertEqual(missing_placeholders("p.concept", PIPELINE_TEMPLATES["concept"]), [])
        self.assertIn("listed", missing_placeholders("p.concept", "без плейсхолдеров"))
        self.assertEqual(missing_placeholders("sys", "любой текст"), [])

    def test_parent_navigation_and_defaults(self):
        self.assertEqual(parent_callback("sys"), "admin:prcat:general")
        self.assertEqual(parent_callback("p.format"), "admin:prcat:pipeline")
        self.assertEqual(parent_callback("i.love"), "admin:prprod:love")
        self.assertTrue(parent_callback("s.personality.0").startswith("admin:prpage:personality:"))
        self.assertEqual(default_prompt_text("sys"), SYSTEM_PROMPT)
        self.assertTrue(is_known_prompt_key("i.compatibility"))
        self.assertFalse(is_known_prompt_key("s.love.999"))

    def test_assembled_prompt_keeps_all_default_sections(self):
        apply_prompt_overrides(None)
        intro, blocks = product_prompt_parts("love")
        self.assertTrue(intro.startswith("СОЗДАЙ ПОЛНЫЙ ЛЮБОВНЫЙ РАЗБОР"))
        self.assertEqual(len(blocks), 18)
        assembled = assembled_product_prompt("love")
        self.assertIn("КАКОЙ ПАРТНЁР ТЕБЕ ПОДХОДИТ", assembled)
        self.assertIn("Где возможна встреча", assembled)
        self.assertIn("Внешние черты", assembled)
        self.assertIn("Внутренние черты", assembled)

    def test_admin_prompt_tree_callbacks(self):
        root = [btn.callback_data for row in prompts_root_menu().inline_keyboard for btn in row]
        self.assertIn("admin:prcat:general", root)
        self.assertIn("admin:prcat:products", root)
        self.assertIn("admin:prcat:pipeline", root)
        products = [btn.callback_data for row in products_menu().inline_keyboard for btn in row]
        self.assertIn("admin:prprod:compatibility", products)
        self.assertIn("admin:prprod:love_free", products)
        buttons = [btn.text for row in edit_keyboard("sys", custom=False).inline_keyboard for btn in row]
        self.assertIn("По умолчанию", buttons)
        changed = [btn.text for row in edit_keyboard("sys", custom=True).inline_keyboard for btn in row]
        self.assertIn("По умолчанию", changed)

    def test_current_prompts_are_stored_as_defaults_and_can_be_restored(self):
        import asyncio
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from database.repository import (
            ensure_prompt_defaults,
            get_active_prompts,
            get_prompt_default,
            init_db,
            restore_prompt_default,
            set_prompt_override,
        )

        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "prompts.db"
                with patch(
                    "database.repository.settings",
                    SimpleNamespace(database_path=db_path),
                ):
                    await init_db()
                    stored = await get_prompt_default("sys")
                    self.assertEqual(stored, SYSTEM_PROMPT)
                    await set_prompt_override("sys", "кастомный системный промпт")
                    active = await get_active_prompts()
                    self.assertEqual(active["sys"], "кастомный системный промпт")
                    restored = await restore_prompt_default("sys")
                    self.assertEqual(restored, SYSTEM_PROMPT)
                    active = await get_active_prompts()
                    self.assertEqual(active["sys"], SYSTEM_PROMPT)
                    await ensure_prompt_defaults()
                    self.assertEqual(await get_prompt_default("sys"), SYSTEM_PROMPT)

        asyncio.run(run())
