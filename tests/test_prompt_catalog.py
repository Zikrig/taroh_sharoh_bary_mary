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
    build_product_keyboard,
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
    SECTION_MAX_WORDS,
    SYSTEM_PROMPT,
    apply_prompt_overrides,
    apply_section_meta,
    assembled_product_prompt,
    default_product_parts,
    product_prompt_for_titles,
    product_prompt_parts,
    section_max_words,
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
            for prefix in (
                "admin:predit:",
                "admin:prreset:",
                "admin:prfile:",
                "admin:prwe:",
                "admin:prren:",
            ):
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
        self.assertNotIn("✏️ Переименовать", buttons)
        changed = [btn.text for row in edit_keyboard("sys", custom=True).inline_keyboard for btn in row]
        self.assertIn("По умолчанию", changed)
        section_on = [
            btn.text
            for row in edit_keyboard("s.love.0", custom=False, enabled=True).inline_keyboard
            for btn in row
        ]
        self.assertIn("✏️ Переименовать", section_on)
        self.assertIn("🟢 Включён", section_on)
        intro_on = [
            btn.text
            for row in edit_keyboard("i.love", custom=False, enabled=True).inline_keyboard
            for btn in row
        ]
        self.assertIn("✏️ Переименовать", intro_on)
        self.assertIn("🟢 Включён", intro_on)
        section_off = [
            btn.text
            for row in edit_keyboard("s.love.0", custom=True, enabled=False).inline_keyboard
            for btn in row
        ]
        self.assertIn("🔴 Выключен", section_off)

    def test_product_screen_lists_intro_beside_section_toggles(self):
        markup, page, pages, total = build_product_keyboard(
            "love_free",
            custom=set(),
            overrides={},
            page=0,
        )
        self.assertEqual(page, 0)
        self.assertEqual(total, len(SECTIONS["love_free"]))
        rows = markup.inline_keyboard
        self.assertEqual(len(rows[0]), 1)
        self.assertTrue(rows[0][0].text.startswith("🟢"))
        self.assertEqual(rows[0][0].callback_data, "admin:predit:i.love_free")
        self.assertEqual(len(rows[1]), 1)
        self.assertTrue(rows[1][0].text.startswith("🟢"))
        self.assertEqual(rows[1][0].callback_data, "admin:predit:s.love_free.0")
        texts = [btn.text for row in rows for btn in row]
        self.assertFalse(any(text.startswith("Разделы") for text in texts))
        self.assertFalse(any(btn.callback_data and btn.callback_data.startswith("admin:prsw:") for row in rows for btn in row))
        disabled, _, _, _ = build_product_keyboard(
            "love_free",
            custom=set(),
            overrides={
                "on.love_free.0": "0",
                "t.love_free.0": "Новое имя",
                "on.love_free.intro": "0",
                "t.love_free.intro": "Старт",
            },
            page=0,
        )
        self.assertTrue(disabled.inline_keyboard[0][0].text.startswith("🔴"))
        self.assertIn("Старт", disabled.inline_keyboard[0][0].text)
        self.assertTrue(disabled.inline_keyboard[1][0].text.startswith("🔴"))
        self.assertIn("Новое имя", disabled.inline_keyboard[1][0].text)

    def test_section_disable_and_rename_change_generation_catalog(self):
        original = SECTIONS["love"][0][0]
        apply_prompt_overrides({"on.love.0": "0", "t.love.1": "Другое имя"})
        active = apply_section_meta("love", SECTIONS["love"])
        titles = [title for title, _ in active]
        self.assertNotIn(original, titles)
        self.assertIn("Другое имя", titles)
        self.assertEqual(len(active), len(SECTIONS["love"]) - 1)
        intro, blocks = product_prompt_parts("love")
        self.assertIn("Другое имя", blocks[1][0])
        prompt = product_prompt_for_titles("love", ["Другое имя"])
        self.assertIn("Другое имя", prompt)
        self.assertIn("Сейчас напиши ТОЛЬКО раздел «Другое имя»", prompt)
        self.assertEqual(
            section_max_words("love", "Другое имя"),
            SECTION_MAX_WORDS["love"][SECTIONS["love"][1][0]],
        )
        apply_prompt_overrides({"on.love.intro": "0"})
        intro, _blocks = product_prompt_parts("love")
        self.assertEqual(intro, "")
        assembled = assembled_product_prompt("love")
        self.assertFalse(assembled.startswith("СОЗДАЙ ПОЛНЫЙ ЛЮБОВНЫЙ РАЗБОР"))

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

    def test_saving_prompt_clears_admin_cached_reports(self):
        import asyncio
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch

        from database.repository import (
            init_db,
            save_free_generation,
            get_free_generation,
            birth_fingerprint,
        )
        from handlers.admin_prompts import _refresh_overrides
        from handlers.router import (
            PENDING_FREE_REPORTS,
            PENDING_FREE_REPORT_IDS_BY_USER,
            store_pending_free_report,
            resolve_pending_free_report,
        )
        from services.ai import _REPORT_CACHE, _remember_report, clear_report_cache

        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "prompts.db"
                with patch(
                    "database.repository.settings",
                    SimpleNamespace(database_path=db_path),
                ), patch(
                    "handlers.admin_prompts.settings",
                    SimpleNamespace(database_path=db_path, admin_ids=(11,)),
                ):
                    await init_db()
                    _remember_report("stale", {"title": "старый разбор"})
                    PENDING_FREE_REPORTS.clear()
                    PENDING_FREE_REPORT_IDS_BY_USER.clear()
                    store_pending_free_report(
                        11,
                        "love",
                        [{"title": "Как ты влюбляешься", "content": "админ"}],
                        admin_mode=True,
                    )
                    store_pending_free_report(
                        22,
                        "love",
                        [{"title": "Как ты влюбляешься", "content": "пользователь"}],
                    )
                    fp = birth_fingerprint(
                        {"date": "1990-01-01", "time": "12:00", "latitude": 55.7, "longitude": 37.6}
                    )
                    await save_free_generation(
                        11,
                        "love",
                        [{"title": "Как ты влюбляешься", "content": "админ"}],
                        fp,
                    )
                    await save_free_generation(
                        22,
                        "love",
                        [{"title": "Как ты влюбляешься", "content": "пользователь"}],
                        fp,
                    )
                    await _refresh_overrides()
                    self.assertEqual(_REPORT_CACHE, {})
                    self.assertIsNone(resolve_pending_free_report(11, None))
                    kept_pending = resolve_pending_free_report(22, None)
                    self.assertIsNotNone(kept_pending)
                    self.assertEqual(
                        kept_pending["sections"][0]["content"], "пользователь"
                    )
                    self.assertIsNone(await get_free_generation(11, "love", fp))
                    kept = await get_free_generation(22, "love", fp)
                    self.assertEqual(kept[0]["content"], "пользователь")
                    clear_report_cache()
                    PENDING_FREE_REPORTS.clear()
                    PENDING_FREE_REPORT_IDS_BY_USER.clear()

        asyncio.run(run())
