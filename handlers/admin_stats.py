"""Admin statistics: tracking links, visits and paid/free reports."""

from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, CopyTextButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.repository import (
    create_tracking_source,
    delete_tracking_source,
    get_report_stats,
    get_stats_overview,
    get_visit_stats,
    list_tracking_sources,
    tracking_source_exists,
)
from handlers.router import _edit_or_answer, is_admin
from services.tracking import (
    PERIODS,
    format_overview_text,
    format_reports_text,
    format_source_text,
    format_visits_text,
    normalize_tracking_slug,
    parse_custom_period,
    period_bounds,
    tracking_link,
)

router = Router()
SOURCES_PAGE_SIZE = 8


class StatsStates(StatesGroup):
    waiting_slug = State()
    waiting_period = State()


def _bounds(period: str, custom: tuple[date, date] | None) -> tuple[str | None, str | None]:
    return period_bounds(period, custom=custom)


async def _guard(callback: CallbackQuery) -> bool:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return False
    return True


def overview_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="🚪 Заходы без ссылки", callback_data="admin:stv:o:all")
    builder.button(text="📈 Прогнозы", callback_data="admin:str:all")
    builder.button(text="🔗 Источники", callback_data="admin:stl:0")
    builder.button(text="➕ Новая ссылка", callback_data="admin:sta")
    builder.button(text="⬅️ Назад", callback_data="admin:back")
    builder.adjust(1)
    return builder.as_markup()


def sources_menu(sources: list[dict], page: int = 0):
    builder = InlineKeyboardBuilder()
    total = len(sources)
    pages = max(1, (total + SOURCES_PAGE_SIZE - 1) // SOURCES_PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    start = page * SOURCES_PAGE_SIZE
    chunk = sources[start : start + SOURCES_PAGE_SIZE]
    for item in chunk:
        slug = item["slug"]
        visits = int(item.get("visits") or 0)
        builder.button(text=f"{slug} · {visits}", callback_data=f"admin:sts:{slug}:all")
    builder.adjust(1)
    nav = []
    if page > 0:
        nav.append(("⬅️", f"admin:stl:{page - 1}"))
    if page + 1 < pages:
        nav.append(("➡️", f"admin:stl:{page + 1}"))
    if nav:
        for text, data in nav:
            builder.button(text=text, callback_data=data)
        builder.adjust(1, *[1] * len(chunk), len(nav))
    builder.button(text="➕ Новая ссылка", callback_data="admin:sta")
    builder.button(text="⬅️ К статистике", callback_data="admin:stats")
    builder.adjust(1)
    return builder.as_markup(), page, pages


def source_detail_menu(slug: str, period: str, link: str):
    builder = InlineKeyboardBuilder()
    for code, label in PERIODS:
        mark = "· " if code == period else ""
        builder.button(text=f"{mark}{label}", callback_data=f"admin:sts:{slug}:{code}")
    builder.button(
        text=("· 📅 Интервал" if period == "c" else "📅 Интервал"),
        callback_data=f"admin:stc:s:{slug}",
    )
    builder.button(text="📋 Скопировать ссылку", copy_text=CopyTextButton(text=link))
    builder.button(text="🗑 Удалить источник", callback_data=f"admin:std:{slug}")
    builder.button(text="⬅️ К источникам", callback_data="admin:stl:0")
    builder.adjust(2, 2, 2, 1, 1, 1)
    return builder.as_markup()


def visits_menu(period: str):
    builder = InlineKeyboardBuilder()
    for code, label in PERIODS:
        mark = "· " if code == period else ""
        builder.button(text=f"{mark}{label}", callback_data=f"admin:stv:o:{code}")
    builder.button(text=("· 📅 Интервал" if period == "c" else "📅 Интервал"), callback_data="admin:stc:o")
    builder.button(text="⬅️ К статистике", callback_data="admin:stats")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def reports_menu(period: str):
    builder = InlineKeyboardBuilder()
    for code, label in PERIODS:
        mark = "· " if code == period else ""
        builder.button(text=f"{mark}{label}", callback_data=f"admin:str:{code}")
    builder.button(text=("· 📅 Интервал" if period == "c" else "📅 Интервал"), callback_data="admin:stc:r")
    builder.button(text="⬅️ К статистике", callback_data="admin:stats")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


async def _bot_username(message: Message) -> str:
    me = await message.bot.get_me()
    return me.username or "bot"


async def show_overview(message: Message) -> None:
    overview = await get_stats_overview()
    await _edit_or_answer(message, format_overview_text(overview), reply_markup=overview_menu())


async def show_organic(message: Message, period: str, custom: tuple[date, date] | None) -> None:
    start, end = _bounds(period, custom)
    stats = await get_visit_stats(organic_only=True, start=start, end=end)
    await _edit_or_answer(
        message,
        format_visits_text(
            title="🚪 Заходы без ссылки",
            period=period,
            visits=stats["visits"],
            unique=stats["unique"],
            custom=custom,
            extra_lines=["Это /start без аргумента — обычный вход в бота."],
        ),
        reply_markup=visits_menu(period),
    )


async def show_reports(message: Message, period: str, custom: tuple[date, date] | None) -> None:
    start, end = _bounds(period, custom)
    stats = await get_report_stats(start=start, end=end)
    await _edit_or_answer(
        message,
        format_reports_text(stats, period=period, custom=custom),
        reply_markup=reports_menu(period),
    )


async def show_sources(message: Message, page: int = 0) -> None:
    sources = await list_tracking_sources()
    markup, page, pages = sources_menu(sources, page)
    if sources:
        text = "🔗 Источники\n\nНажмите источник, чтобы скопировать ссылку и посмотреть статистику."
        if pages > 1:
            text += f"\n{page + 1}/{pages}"
    else:
        text = (
            "🔗 Источники\n\n"
            "Пока нет ссылок. Добавьте код, например inst — получите "
            "https://t.me/бот?start=inst"
        )
    await _edit_or_answer(message, text, reply_markup=markup)


async def show_source(
    message: Message,
    slug: str,
    period: str,
    custom: tuple[date, date] | None,
) -> None:
    start, end = _bounds(period, custom)
    visits = await get_visit_stats(source_slug=slug, start=start, end=end)
    reports = await get_report_stats(source_slug=slug, start=start, end=end)
    username = await _bot_username(message)
    link = tracking_link(username, slug)
    await _edit_or_answer(
        message,
        format_source_text(
            slug=slug,
            link=link,
            period=period,
            visits=visits["visits"],
            unique=visits["unique"],
            reports=reports,
            custom=custom,
        ),
        reply_markup=source_detail_menu(slug, period, link),
        parse_mode=ParseMode.HTML,
    )


@router.callback_query(F.data == "admin:stats")
async def open_stats(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    await state.clear()
    await callback.answer()
    await show_overview(callback.message)


@router.callback_query(F.data.startswith("admin:stv:o:"))
async def open_organic(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    period = (callback.data or "").rsplit(":", 1)[-1]
    if period == "c":
        await ask_custom_period(callback, state, scope="organic")
        return
    if period not in dict(PERIODS):
        await callback.answer("Неизвестный период", show_alert=True)
        return
    await state.update_data(stats_period=period, stats_from=None, stats_to=None)
    await callback.answer()
    await show_organic(callback.message, period, None)


@router.callback_query(F.data.startswith("admin:str:"))
async def open_reports(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    period = (callback.data or "").rsplit(":", 1)[-1]
    if period == "c":
        await ask_custom_period(callback, state, scope="reports")
        return
    if period not in dict(PERIODS):
        await callback.answer("Неизвестный период", show_alert=True)
        return
    await state.update_data(stats_period=period, stats_from=None, stats_to=None)
    await callback.answer()
    await show_reports(callback.message, period, None)


@router.callback_query(F.data.startswith("admin:stl:"))
async def open_sources(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    try:
        page = int((callback.data or "").rsplit(":", 1)[-1])
    except ValueError:
        page = 0
    await state.clear()
    await callback.answer()
    await show_sources(callback.message, page)


@router.callback_query(F.data.startswith("admin:sts:"))
async def open_source(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    payload = (callback.data or "")[len("admin:sts:") :]
    if ":" not in payload:
        await callback.answer("Источник не найден", show_alert=True)
        return
    slug, period = payload.rsplit(":", 1)
    slug = normalize_tracking_slug(slug) or ""
    if not slug or not await tracking_source_exists(slug):
        await callback.answer("Источник не найден", show_alert=True)
        return
    if period == "c":
        await ask_custom_period(callback, state, scope="source", slug=slug)
        return
    if period not in dict(PERIODS):
        await callback.answer("Неизвестный период", show_alert=True)
        return
    await state.update_data(
        stats_period=period,
        stats_slug=slug,
        stats_from=None,
        stats_to=None,
    )
    await callback.answer()
    await show_source(callback.message, slug, period, None)


@router.callback_query(F.data == "admin:sta")
async def start_add_source(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    await callback.answer()
    await state.set_state(StatsStates.waiting_slug)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin:stats")
    await callback.message.answer(
        "Отправьте код ссылки латиницей, например: <code>inst</code>\n\n"
        "Появится ссылка вида https://t.me/бот?start=inst\n"
        "Можно: буквы, цифры, _ и - , до 32 символов.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("admin:std:"))
async def confirm_delete_source(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    slug = normalize_tracking_slug((callback.data or "")[len("admin:std:") :]) or ""
    if not slug:
        await callback.answer("Источник не найден", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data=f"admin:stxd:{slug}")
    builder.button(text="Отмена", callback_data=f"admin:sts:{slug}:all")
    builder.adjust(1)
    await _edit_or_answer(
        callback.message,
        f"Удалить источник «{slug}»?\nСсылка пропадёт из списка, уже посчитанные заходы сохранятся.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("admin:stxd:"))
async def delete_source(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    slug = normalize_tracking_slug((callback.data or "")[len("admin:stxd:") :]) or ""
    if slug:
        await delete_tracking_source(slug)
    await state.clear()
    await callback.answer("Источник удалён")
    await show_sources(callback.message, 0)


@router.callback_query(F.data.startswith("admin:stc:"))
async def custom_period_callback(callback: CallbackQuery, state: FSMContext):
    if not await _guard(callback):
        return
    rest = (callback.data or "")[len("admin:stc:") :]
    if rest == "o":
        await ask_custom_period(callback, state, scope="organic")
        return
    if rest == "r":
        await ask_custom_period(callback, state, scope="reports")
        return
    if rest.startswith("s:"):
        slug = normalize_tracking_slug(rest[2:]) or ""
        await ask_custom_period(callback, state, scope="source", slug=slug)
        return
    await callback.answer("Неизвестный запрос", show_alert=True)


async def ask_custom_period(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    scope: str,
    slug: str | None = None,
) -> None:
    await callback.answer()
    await state.set_state(StatsStates.waiting_period)
    await state.update_data(stats_scope=scope, stats_slug=slug or "")
    back = {
        "organic": "admin:stv:o:all",
        "reports": "admin:str:all",
        "source": f"admin:sts:{slug}:all" if slug else "admin:stats",
    }[scope]
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data=back)
    await callback.message.answer(
        "Отправьте период в формате:\n"
        "<code>01.08.2026 — 21.08.2026</code>\n\n"
        "Или одну дату, чтобы посмотреть один день.",
        parse_mode=ParseMode.HTML,
        reply_markup=builder.as_markup(),
    )


@router.message(StatsStates.waiting_slug, F.text, ~F.text.startswith("/"))
async def save_new_source(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    slug = normalize_tracking_slug(text)
    if not slug:
        await message.answer(
            "Код не подходит. Латиница, цифры, _ или - , без пробелов, до 32 символов.\n"
            "Пример: inst"
        )
        return
    created = await create_tracking_source(slug)
    if not created:
        await message.answer(f"Источник «{slug}» уже есть. Откройте его в списке или введите другой код.")
        return
    await state.clear()
    await show_source(message, slug, "all", None)


@router.message(StatsStates.waiting_period, F.text, ~F.text.startswith("/"))
async def save_custom_period(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    parsed = parse_custom_period(text)
    if not parsed:
        await message.answer("Не получилось прочитать даты. Пример: 01.08.2026 — 21.08.2026")
        return
    start, end = parsed
    data = await state.get_data()
    scope = str(data.get("stats_scope") or "organic")
    slug = normalize_tracking_slug(str(data.get("stats_slug") or "")) or ""
    await state.clear()
    custom = (start, end)
    if scope == "reports":
        await show_reports(message, "c", custom)
    elif scope == "source" and slug:
        await show_source(message, slug, "c", custom)
    else:
        await show_organic(message, "c", custom)
