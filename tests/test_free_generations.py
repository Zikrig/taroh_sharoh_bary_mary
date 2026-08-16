import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from database.repository import (
    birth_fingerprint,
    get_free_generation,
    init_db,
    save_free_generation,
)
from services.ai import _prior_free_block


def _chart(date: str = "1990-01-01", time: str = "12:00", lat: float = 55.75, lon: float = 37.62) -> dict:
    return {"date": date, "time": time, "latitude": lat, "longitude": lon}


class FreeGenerationsTests(unittest.TestCase):
    def test_birth_fingerprint_changes_with_date(self):
        a = birth_fingerprint(_chart("1990-01-01"))
        b = birth_fingerprint(_chart("1991-01-01"))
        self.assertNotEqual(a, b)
        pair = birth_fingerprint(_chart(), _chart("1992-02-02"))
        self.assertIn("||", pair)

    def test_prior_free_block_asks_to_expand(self):
        block = _prior_free_block(
            [{"title": "Твой портрет", "content": "Ты заметный и спокойный."}]
        )
        lower = block.lower()
        self.assertIn("смысловая основа", lower)
        self.assertIn("расширять", lower)
        self.assertIn("твой портрет", lower)

    def test_save_keeps_only_last_and_requires_fingerprint_match(self):
        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "test.db"
                with patch(
                    "database.repository.settings",
                    SimpleNamespace(database_path=db_path),
                ):
                    await init_db()
                    fp_a = birth_fingerprint(_chart("1990-01-01"))
                    fp_b = birth_fingerprint(_chart("1991-01-01"))
                    await save_free_generation(
                        42,
                        "personality",
                        [{"title": "Твой портрет", "content": "раз"}],
                        fp_a,
                    )
                    await save_free_generation(
                        42,
                        "love",
                        [{"title": "Как ты влюбляешься", "content": "два"}],
                        fp_a,
                    )
                    # Newer scenario replaces the previous free report.
                    self.assertIsNone(
                        await get_free_generation(42, "personality", fp_a)
                    )
                    love = await get_free_generation(42, "love", fp_a)
                    self.assertIsNotNone(love)
                    self.assertEqual(love[0]["content"], "два")
                    # Birth data mismatch drops prior free context.
                    self.assertIsNone(await get_free_generation(42, "love", fp_b))
                    self.assertIsNone(await get_free_generation(42, "love", ""))

        asyncio.run(run())

    def test_legacy_table_migrates_to_one_row_per_user(self):
        async def run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "legacy.db"
                with patch(
                    "database.repository.settings",
                    SimpleNamespace(database_path=db_path),
                ):
                    import aiosqlite

                    async with aiosqlite.connect(db_path) as db:
                        await db.execute(
                            """
                            CREATE TABLE free_generations (
                                user_id INTEGER NOT NULL,
                                scenario TEXT NOT NULL,
                                sections_json TEXT NOT NULL,
                                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                                PRIMARY KEY (user_id, scenario)
                            )
                            """
                        )
                        await db.execute(
                            """
                            INSERT INTO free_generations (user_id, scenario, sections_json, updated_at)
                            VALUES
                            (7, 'personality', '[{"title":"A","content":"old"}]', '2020-01-01 00:00:00'),
                            (7, 'love', '[{"title":"B","content":"new"}]', '2024-01-01 00:00:00')
                            """
                        )
                        await db.commit()
                    await init_db()
                    # Empty fingerprint from migration → get requires non-empty match.
                    self.assertIsNone(
                        await get_free_generation(7, "love", "anything")
                    )
                    async with aiosqlite.connect(db_path) as db:
                        async with db.execute(
                            "SELECT scenario, sections_json FROM free_generations WHERE user_id = 7"
                        ) as cur:
                            rows = await cur.fetchall()
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0][0], "love")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
