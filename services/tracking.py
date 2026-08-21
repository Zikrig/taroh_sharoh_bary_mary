"""Deep-link slugs, date periods and admin stats text."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

STATS_TZ = ZoneInfo("Europe/Moscow")

SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_DATE_PATTERN = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})")
PERIODS: tuple[tuple[str, str], ...] = (
    ("all", "Всё время"),
    ("d1", "Сегодня"),
    ("d3", "3 дня"),
    ("w", "Неделя"),
    ("m", "Месяц"),
)
PERIOD_LABELS = dict(PERIODS)
REPORT_TYPE_ORDER = ("personality", "love", "money", "compatibility")
REPORT_TYPE_LABELS = {
    "personality": "Личность",
    "love": "Любовь",
    "money": "Деньги",
    "compatibility": "Совместимость",
}


def normalize_tracking_slug(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if raw.startswith("start="):
        raw = raw[6:].strip()
    if not SLUG_PATTERN.fullmatch(raw):
        return None
    return raw.casefold()


def tracking_link(bot_username: str, slug: str) -> str:
    name = str(bot_username or "").lstrip("@").strip()
    return f"https://t.me/{name}?start={slug}"


def _utc_naive(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def period_bounds(
    period: str,
    *,
    now: datetime | None = None,
    custom: tuple[date, date] | None = None,
) -> tuple[str | None, str | None]:
    """Inclusive calendar range in Moscow, returned as UTC [start, end)."""
    if period == "all":
        return None, None
    current = now or datetime.now(STATS_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=STATS_TZ)
    else:
        current = current.astimezone(STATS_TZ)
    today = current.date()
    if period == "c":
        if not custom:
            return None, None
        start_day, end_day = custom
        if start_day > end_day:
            start_day, end_day = end_day, start_day
        start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=STATS_TZ)
        end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=STATS_TZ) + timedelta(
            days=1
        )
        return _utc_naive(start), _utc_naive(end)
    days = {"d1": 1, "d3": 3, "w": 7, "m": 30}.get(period)
    if not days:
        return None, None
    start_day = today - timedelta(days=days - 1)
    start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=STATS_TZ)
    tomorrow = today + timedelta(days=1)
    end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=STATS_TZ)
    return _utc_naive(start), _utc_naive(end)


def parse_custom_period(text: str) -> tuple[date, date] | None:
    matches = _DATE_PATTERN.findall(text or "")
    if not matches:
        return None
    parsed: list[date] = []
    for day, month, year in matches[:2]:
        try:
            parsed.append(date(int(year), int(month), int(day)))
        except ValueError:
            return None
    if len(parsed) == 1:
        return parsed[0], parsed[0]
    start, end = parsed
    if start > end:
        start, end = end, start
    return start, end


def period_caption(period: str, custom: tuple[date, date] | None = None) -> str:
    if period == "c" and custom:
        start, end = custom
        if start == end:
            return start.strftime("%d.%m.%Y")
        return f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"
    return PERIOD_LABELS.get(period, "Всё время")


def ru_plural(count: int, one: str, few: str, many: str) -> str:
    value = abs(int(count)) % 100
    if 11 <= value <= 14:
        return many
    last = value % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def format_people(count: int) -> str:
    word = ru_plural(count, "человек", "человека", "человек")
    return f"{count} {word}"


def format_visits_line(visits: int, unique: int) -> str:
    visit_word = ru_plural(visits, "заход", "захода", "заходов")
    return f"{visits} {visit_word} · {format_people(unique)}"


def _by_type_lines(by_type: dict[str, int]) -> list[str]:
    lines: list[str] = []
    known = set(REPORT_TYPE_ORDER)
    for report_type in REPORT_TYPE_ORDER:
        count = int(by_type.get(report_type) or 0)
        if count:
            lines.append(f"• {REPORT_TYPE_LABELS[report_type]}: {count}")
    extra = sorted(key for key in by_type if key not in known and by_type[key])
    for report_type in extra:
        lines.append(f"• {report_type}: {by_type[report_type]}")
    return lines


def format_overview_text() -> str:
    return "📊 Статистика"


def format_visits_text(
    *,
    title: str,
    period: str,
    visits: int,
    unique: int,
    custom: tuple[date, date] | None = None,
    extra_lines: list[str] | None = None,
) -> str:
    lines = [
        title,
        f"Период: {period_caption(period, custom)}",
        "",
        format_visits_line(visits, unique),
    ]
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)
    return "\n".join(lines)


def format_reports_text(
    stats: dict[str, Any],
    *,
    period: str,
    custom: tuple[date, date] | None = None,
) -> str:
    free = stats["free"]
    paid = stats["paid"]
    lines = [
        "Заказы",
        f"Период: {period_caption(period, custom)}",
        "",
        f"Бесплатные: {free['total']} · {format_people(free['unique'])}",
    ]
    lines.extend(_by_type_lines(free.get("by_type") or {}))
    lines.append("")
    paid_line = f"Платные: {paid['total']} · {format_people(paid['unique'])}"
    if paid.get("stars"):
        paid_line += f" · {paid['stars']}⭐"
    lines.append(paid_line)
    lines.extend(_by_type_lines(paid.get("by_type") or {}))
    return "\n".join(lines)


def format_source_text(
    *,
    slug: str,
    link: str,
    period: str,
    visits: int,
    unique: int,
    reports: dict[str, Any],
    custom: tuple[date, date] | None = None,
) -> str:
    free_total = reports["free"]["total"]
    paid_total = reports["paid"]["total"]
    paid_stars = reports["paid"].get("stars") or 0
    lines = [
        f"Ссылка: <b>{slug}</b>",
        f"Период: {period_caption(period, custom)}",
        "",
        f"<code>{link}</code>",
        "",
        f"Заходы: {format_visits_line(visits, unique)}",
        f"Бесплатные заказы: {free_total}",
        f"Платные заказы: {paid_total}" + (f" · {paid_stars}⭐" if paid_stars else ""),
    ]
    return "\n".join(lines)
