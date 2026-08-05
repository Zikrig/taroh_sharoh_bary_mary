from pathlib import Path
from typing import Any

import aiosqlite

from config.settings import settings


async def init_db() -> None:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.database_path) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                birth_date TEXT NOT NULL,
                birth_time TEXT NOT NULL,
                birth_place TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                report_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                telegram_payment_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('test_mode', '0');
            """
        )
        await db.commit()


async def get_test_mode() -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = 'test_mode'"
        ) as cur:
            row = await cur.fetchone()
            return bool(row and row[0] == "1")


async def set_test_mode(enabled: bool) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO app_settings (key, value) VALUES ('test_mode', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            ("1" if enabled else "0",),
        )
        await db.commit()


async def get_app_setting(key: str) -> str | None:
    async with aiosqlite.connect(settings.database_path) as db:
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_app_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        await db.commit()


async def get_profile(user_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def save_profile(user_id: int, profile: dict[str, Any]) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO profiles (user_id, birth_date, birth_time, birth_place, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                birth_date=excluded.birth_date, birth_time=excluded.birth_time,
                birth_place=excluded.birth_place, latitude=excluded.latitude,
                longitude=excluded.longitude, updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, profile["birth_date"], profile["birth_time"], profile["birth_place"],
             profile["latitude"], profile["longitude"]),
        )
        await db.commit()


async def create_order(user_id: int, report_type: str, amount: int) -> int:
    async with aiosqlite.connect(settings.database_path) as db:
        cur = await db.execute(
            "INSERT INTO orders (user_id, report_type, amount) VALUES (?, ?, ?)",
            (user_id, report_type, amount),
        )
        await db.commit()
        return cur.lastrowid


async def complete_order(order_id: int, payment_id: str) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            "UPDATE orders SET status='paid', telegram_payment_id=? WHERE id=?",
            (payment_id, order_id),
        )
        await db.commit()
