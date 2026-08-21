import asyncio
import tempfile
import unittest
from datetime import date, datetime
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
from zoneinfo import ZoneInfo

if find_spec("swisseph") is None:
    sys.modules["swisseph"] = SimpleNamespace(
        SUN=0, MOON=1, MERCURY=2, VENUS=3, MARS=4, JUPITER=5,
        SATURN=6, URANUS=7, NEPTUNE=8, PLUTO=9,
    )

from database.repository import (
    create_order,
    complete_order,
    create_tracking_source,
    get_report_stats,
    get_stats_overview,
    get_visit_stats,
    init_db,
    list_tracking_sources,
    record_bot_visit,
    record_report_event,
)
from handlers.admin_stats import overview_menu, source_detail_menu
from services.tracking import (
    normalize_tracking_slug,
    parse_custom_period,
    period_bounds,
    tracking_link,
)


MSK = ZoneInfo("Europe/Moscow")


def _run(coro):
    return asyncio.run(coro)


class TrackingStatsTests(unittest.TestCase):
    def test_slug_and_link(self):
        self.assertEqual(normalize_tracking_slug(" Inst "), "inst")
        self.assertEqual(normalize_tracking_slug("vk-ads_1"), "vk-ads_1")
        self.assertIsNone(normalize_tracking_slug("инст"))
        self.assertIsNone(normalize_tracking_slug("a b"))
        self.assertIsNone(normalize_tracking_slug(""))
        self.assertEqual(
            tracking_link("astro_mary_bot", "inst"),
            "https://t.me/astro_mary_bot?start=inst",
        )

    def test_overview_menu_lists_orders_visits_and_links(self):
        markup, _, _ = overview_menu(
            [{"slug": "inst", "visits": 3}, {"slug": "vk", "visits": 1}]
        )
        texts = [button.text for row in markup.inline_keyboard for button in row]
        self.assertEqual(
            texts,
            ["Заказы", "Заходы без ссылки", "inst", "vk", "Новая ссылка", "⬅️ Назад"],
        )

    def test_source_copy_callback_fits_telegram_limit(self):
        slug = "a" * 32
        markup = source_detail_menu(slug, "all", tracking_link("bot", slug))
        for row in markup.inline_keyboard:
            for button in row:
                if button.callback_data:
                    self.assertLessEqual(len(button.callback_data), 64, button.callback_data)

    def test_custom_period_parsing(self):
        self.assertEqual(
            parse_custom_period("01.08.2026 — 21.08.2026"),
            (date(2026, 8, 1), date(2026, 8, 21)),
        )
        self.assertEqual(parse_custom_period("05.08.2026"), (date(2026, 8, 5), date(2026, 8, 5)))
        swapped = parse_custom_period("21.08.2026-01.08.2026")
        self.assertEqual(swapped, (date(2026, 8, 1), date(2026, 8, 21)))
        self.assertIsNone(parse_custom_period("просто текст"))

    def test_today_bounds_are_moscow_calendar_day(self):
        now = datetime(2026, 8, 21, 1, 0, tzinfo=MSK)
        start, end = period_bounds("d1", now=now)
        self.assertEqual(start, "2026-08-20 21:00:00")
        self.assertEqual(end, "2026-08-21 21:00:00")
        self.assertEqual(period_bounds("all"), (None, None))
        custom = period_bounds("c", custom=(date(2026, 8, 1), date(2026, 8, 2)))
        self.assertEqual(custom[0], "2026-07-31 21:00:00")
        self.assertEqual(custom[1], "2026-08-02 21:00:00")

    def test_visits_and_reports_split_organic_and_source(self):
        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "test.db"
                with patch(
                    "database.repository.settings",
                    SimpleNamespace(database_path=db_path),
                ):
                    await init_db()
                    self.assertTrue(await create_tracking_source("inst"))
                    self.assertFalse(await create_tracking_source("INST"))
                    await record_bot_visit(1, None)
                    await record_bot_visit(1, "")
                    await record_bot_visit(2, "inst")
                    await record_bot_visit(2, "inst")
                    await record_bot_visit(3, "unknown_ok")
                    organic = await get_visit_stats(organic_only=True)
                    inst = await get_visit_stats(source_slug="inst")
                    total = await get_visit_stats()
                    self.assertEqual(organic["visits"], 2)
                    self.assertEqual(organic["unique"], 1)
                    self.assertEqual(inst["visits"], 2)
                    self.assertEqual(inst["unique"], 1)
                    self.assertEqual(total["visits"], 5)
                    await record_report_event(2, kind="free", report_type="love")
                    await record_report_event(
                        2, kind="paid", report_type="love", amount=399, order_id=15
                    )
                    await record_report_event(
                        2, kind="paid", report_type="love", amount=399, order_id=15
                    )
                    reports = await get_report_stats(source_slug="inst")
                    self.assertEqual(reports["free"]["total"], 1)
                    self.assertEqual(reports["paid"]["total"], 1)
                    self.assertEqual(reports["paid"]["stars"], 399)
                    overview = await get_stats_overview()
                    self.assertEqual(overview["reports"]["paid"]["total"], 1)
                    sources = await list_tracking_sources()
                    self.assertEqual(sources[0]["slug"], "inst")
                    self.assertEqual(sources[0]["visits"], 2)

        _run(run())

    def test_backfill_counts_existing_paid_orders(self):
        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "test.db"
                with patch(
                    "database.repository.settings",
                    SimpleNamespace(database_path=db_path),
                ):
                    await init_db()
                    order_id = await create_order(9, "personality", 349)
                    await complete_order(order_id, "real-charge")
                    await init_db()
                    stats = await get_report_stats()
                    self.assertEqual(stats["paid"]["total"], 1)
                    self.assertEqual(stats["paid"]["stars"], 349)

        _run(run())


if __name__ == "__main__":
    unittest.main()
