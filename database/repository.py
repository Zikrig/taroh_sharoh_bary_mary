import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

from config.settings import settings

FREE_DAILY_TZ = ZoneInfo("Europe/Moscow")

GENDER_FEMALE = "female"
GENDER_MALE = "male"
DEFAULT_GENDER = GENDER_FEMALE


def normalize_gender(value: Any) -> str:
    raw = str(value or "").strip().casefold()
    if raw in {"male", "m", "муж", "мужской", "mars", "♂"}:
        return GENDER_MALE
    return GENDER_FEMALE


def gender_label_ru(value: Any) -> str:
    return "мужчина" if normalize_gender(value) == GENDER_MALE else "женщина"


def gender_symbol(value: Any) -> str:
    return "♂" if normalize_gender(value) == GENDER_MALE else "♀"


async def init_db() -> None:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(settings.database_path) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                birth_date TEXT NOT NULL,
                birth_time TEXT NOT NULL,
                time_is_approximate INTEGER NOT NULL DEFAULT 0,
                birth_place TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                gender TEXT NOT NULL DEFAULT 'female',
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
            CREATE TABLE IF NOT EXISTS report_contexts (
                order_id INTEGER PRIMARY KEY,
                chart_json TEXT NOT NULL,
                second_chart_json TEXT,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );
            CREATE TABLE IF NOT EXISTS free_daily_usage (
                user_id INTEGER PRIMARY KEY,
                last_used_date TEXT NOT NULL
            );
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('test_mode', '0');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('free_daily_limit', '1');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('price_personality', '349');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('price_love', '399');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('price_compatibility', '449');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('price_money', '399');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('model_free', 'deepseek-v4-flash');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('model_pdf', 'deepseek-v4-flash');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('model_review', 'deepseek-v4-pro-0813');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('model_expensive', 'deepseek-v4-pro-0813');
            INSERT OR IGNORE INTO app_settings (key, value)
            VALUES ('model_cheap', 'deepseek-v4-flash');
            """
        )
        columns = {
            row[1] for row in await (await db.execute("PRAGMA table_info(profiles)")).fetchall()
        }
        if "time_is_approximate" not in columns:
            await db.execute(
                "ALTER TABLE profiles ADD COLUMN time_is_approximate INTEGER NOT NULL DEFAULT 0"
            )
        if "gender" not in columns:
            await db.execute(
                "ALTER TABLE profiles ADD COLUMN gender TEXT NOT NULL DEFAULT 'female'"
            )
        # Existing users without an explicit choice are treated as female.
        await db.execute(
            """
            UPDATE profiles
            SET gender = 'female'
            WHERE gender IS NULL OR TRIM(gender) = ''
            """
        )
        await _ensure_free_generations_schema(db)
        await db.commit()


async def _ensure_free_generations_schema(db: aiosqlite.Connection) -> None:
    """One free report per user, with birth fingerprint for paid continuity."""
    tables = {
        row[0]
        for row in await (
            await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='free_generations'"
            )
        ).fetchall()
    }
    if not tables:
        await db.execute(
            """
            CREATE TABLE free_generations (
                user_id INTEGER PRIMARY KEY,
                scenario TEXT NOT NULL,
                sections_json TEXT NOT NULL,
                birth_fingerprint TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        return

    columns = {
        row[1] for row in await (await db.execute("PRAGMA table_info(free_generations)")).fetchall()
    }
    pk_cols = [
        row[1]
        for row in await (await db.execute("PRAGMA table_info(free_generations)")).fetchall()
        if row[5]  # pk ordinal > 0
    ]
    needs_rebuild = pk_cols != ["user_id"] or "birth_fingerprint" not in columns
    if not needs_rebuild:
        return

    await db.execute(
        """
        CREATE TABLE free_generations_new (
            user_id INTEGER PRIMARY KEY,
            scenario TEXT NOT NULL,
            sections_json TEXT NOT NULL,
            birth_fingerprint TEXT NOT NULL DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Keep the newest row per user from the legacy (user_id, scenario) table.
    await db.execute(
        """
        INSERT INTO free_generations_new (user_id, scenario, sections_json, birth_fingerprint, updated_at)
        SELECT user_id, scenario, sections_json, '', updated_at
        FROM (
            SELECT
                user_id,
                scenario,
                sections_json,
                COALESCE(updated_at, '') AS updated_at,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY datetime(updated_at) DESC, rowid DESC
                ) AS rn
            FROM free_generations
        )
        WHERE rn = 1
        """
    )
    await db.execute("DROP TABLE free_generations")
    await db.execute("ALTER TABLE free_generations_new RENAME TO free_generations")


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


async def get_free_daily_limit_enabled() -> bool:
    async with aiosqlite.connect(settings.database_path) as db:
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = 'free_daily_limit'"
        ) as cur:
            row = await cur.fetchone()
            # Default ON when the setting is missing.
            return bool(row is None or row[0] == "1")


async def set_free_daily_limit_enabled(enabled: bool) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO app_settings (key, value) VALUES ('free_daily_limit', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            ("1" if enabled else "0",),
        )
        await db.commit()


def moscow_today() -> str:
    return datetime.now(FREE_DAILY_TZ).date().isoformat()


async def has_used_free_today(user_id: int) -> bool:
    today = moscow_today()
    async with aiosqlite.connect(settings.database_path) as db:
        async with db.execute(
            "SELECT last_used_date FROM free_daily_usage WHERE user_id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
            return bool(row and row[0] == today)


async def mark_free_used_today(user_id: int) -> None:
    today = moscow_today()
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO free_daily_usage (user_id, last_used_date)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_used_date=excluded.last_used_date
            """,
            (user_id, today),
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


DEFAULT_REPORT_PRICES = {
    "personality": 349,
    "love": 399,
    "compatibility": 449,
    "money": 399,
}


async def get_report_prices() -> dict[str, int]:
    prices: dict[str, int] = {}
    for scenario, default in DEFAULT_REPORT_PRICES.items():
        raw = await get_app_setting(f"price_{scenario}")
        try:
            value = int(str(raw).strip()) if raw is not None else default
        except (TypeError, ValueError):
            value = default
        if value < 1:
            value = default
        prices[scenario] = value
    return prices


async def get_report_price(scenario: str) -> int:
    prices = await get_report_prices()
    if scenario not in prices:
        raise KeyError(scenario)
    return prices[scenario]


async def set_report_price(scenario: str, amount: int) -> None:
    if scenario not in DEFAULT_REPORT_PRICES:
        raise KeyError(scenario)
    if amount < 1:
        raise ValueError("price must be >= 1")
    await set_app_setting(f"price_{scenario}", str(amount))


DEFAULT_AI_MODELS = {
    "free": "deepseek-v4-flash",
    "expensive": "deepseek-v4-pro-0813",
    "cheap": "deepseek-v4-flash",
}
AI_MODEL_ROLE_LABELS = {
    "free": "Бесплатные (волны)",
    "expensive": "Скелет PDF",
    "cheap": "Разделы PDF",
}
_LEGACY_MODEL_FALLBACKS = {
    "free": ("model_free",),
    "expensive": ("model_review", "model_pdf"),
    "cheap": ("model_pdf", "model_free"),
}


async def get_ai_models() -> dict[str, str]:
    models: dict[str, str] = {}
    for role, default in DEFAULT_AI_MODELS.items():
        raw = await get_app_setting(f"model_{role}")
        value = str(raw).strip() if raw is not None else ""
        if not value:
            for legacy_key in _LEGACY_MODEL_FALLBACKS.get(role, ()):
                legacy = await get_app_setting(legacy_key)
                if legacy and str(legacy).strip():
                    value = str(legacy).strip()
                    break
        models[role] = value or default
    return models


async def get_ai_model(role: str) -> str:
    models = await get_ai_models()
    if role not in models:
        raise KeyError(role)
    return models[role]


async def set_ai_model(role: str, model_name: str) -> None:
    if role not in DEFAULT_AI_MODELS:
        raise KeyError(role)
    cleaned = model_name.strip()
    if not cleaned:
        raise ValueError("model must not be empty")
    await set_app_setting(f"model_{role}", cleaned)


PDF_SELL_TEXT_KINDS = ("upsell", "offer")


async def get_pdf_sell_text(kind: str, scenario: str, defaults: dict[str, str]) -> str:
    if kind not in PDF_SELL_TEXT_KINDS:
        raise KeyError(kind)
    raw = await get_app_setting(f"pdf_{kind}_{scenario}")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return defaults.get(scenario, "")


async def set_pdf_sell_text(kind: str, scenario: str, text: str) -> None:
    if kind not in PDF_SELL_TEXT_KINDS:
        raise KeyError(kind)
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("text must not be empty")
    await set_app_setting(f"pdf_{kind}_{scenario}", cleaned)


async def get_profile(user_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            profile = dict(row)
            profile["gender"] = normalize_gender(profile.get("gender"))
            return profile


async def save_profile(user_id: int, profile: dict[str, Any]) -> None:
    gender = normalize_gender(profile.get("gender"))
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO profiles (
                user_id, birth_date, birth_time, time_is_approximate,
                birth_place, latitude, longitude, gender
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                birth_date=excluded.birth_date, birth_time=excluded.birth_time,
                time_is_approximate=excluded.time_is_approximate,
                birth_place=excluded.birth_place, latitude=excluded.latitude,
                longitude=excluded.longitude, gender=excluded.gender,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                user_id,
                profile["birth_date"],
                profile["birth_time"],
                int(profile.get("time_is_approximate", False)),
                profile["birth_place"],
                profile["latitude"],
                profile["longitude"],
                gender,
            ),
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


async def save_report_context(
    order_id: int, chart: dict[str, Any], second_chart: dict[str, Any] | None
) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO report_contexts (order_id, chart_json, second_chart_json)
            VALUES (?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                chart_json=excluded.chart_json,
                second_chart_json=excluded.second_chart_json
            """,
            (
                order_id,
                json.dumps(chart, ensure_ascii=False),
                json.dumps(second_chart, ensure_ascii=False) if second_chart else None,
            ),
        )
        await db.commit()


async def get_report_context(order_id: int) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    async with aiosqlite.connect(settings.database_path) as db:
        async with db.execute(
            "SELECT chart_json, second_chart_json FROM report_contexts WHERE order_id = ?",
            (order_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return json.loads(row[0]), json.loads(row[1]) if row[1] else None


def _normalize_stored_sections(sections: list[Any]) -> list[dict[str, str]]:
    stored: list[dict[str, str]] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if title and content:
            stored.append({"title": title, "content": content})
    return stored


def _chart_fingerprint_part(chart: dict[str, Any]) -> str:
    lat = chart.get("latitude")
    lon = chart.get("longitude")
    try:
        lat_s = f"{float(lat):.5f}" if lat is not None else ""
    except (TypeError, ValueError):
        lat_s = ""
    try:
        lon_s = f"{float(lon):.5f}" if lon is not None else ""
    except (TypeError, ValueError):
        lon_s = ""
    date = str(chart.get("date") or chart.get("birth_date") or "").strip()
    time = str(chart.get("time") or chart.get("birth_time") or "").strip()
    return f"{date}|{time}|{lat_s}|{lon_s}"


def birth_fingerprint(
    chart: dict[str, Any],
    second_chart: dict[str, Any] | None = None,
) -> str:
    """Stable identity of natal inputs used for a free/paid report."""
    primary = _chart_fingerprint_part(chart)
    if second_chart:
        return f"{primary}||{_chart_fingerprint_part(second_chart)}"
    return primary


async def save_free_generation(
    user_id: int,
    scenario: str,
    sections: list[dict[str, Any]],
    birth_fingerprint_value: str,
) -> None:
    stored = _normalize_stored_sections(sections)
    if not stored:
        return
    fingerprint = str(birth_fingerprint_value or "").strip()
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO free_generations (user_id, scenario, sections_json, birth_fingerprint)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                scenario=excluded.scenario,
                sections_json=excluded.sections_json,
                birth_fingerprint=excluded.birth_fingerprint,
                updated_at=CURRENT_TIMESTAMP
            """,
            (user_id, scenario, json.dumps(stored, ensure_ascii=False), fingerprint),
        )
        await db.commit()


async def get_free_generation(
    user_id: int,
    scenario: str,
    birth_fingerprint_value: str,
) -> list[dict[str, str]] | None:
    fingerprint = str(birth_fingerprint_value or "").strip()
    async with aiosqlite.connect(settings.database_path) as db:
        async with db.execute(
            """
            SELECT sections_json, scenario, birth_fingerprint FROM free_generations
            WHERE user_id = ?
            """,
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    stored_scenario = str(row[1] or "")
    stored_fingerprint = str(row[2] or "").strip()
    if stored_scenario != scenario or stored_fingerprint != fingerprint or not fingerprint:
        return None
    try:
        parsed = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list):
        return None
    stored = _normalize_stored_sections(parsed)
    return stored or None


async def complete_order(order_id: int, payment_id: str) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            "UPDATE orders SET status='paid', telegram_payment_id=? WHERE id=?",
            (payment_id, order_id),
        )
        await db.commit()


async def set_order_status(order_id: int, status: str) -> None:
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        await db.commit()


async def get_order(order_id: int, user_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(settings.database_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM orders WHERE id=? AND user_id=?",
            (order_id, user_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None
