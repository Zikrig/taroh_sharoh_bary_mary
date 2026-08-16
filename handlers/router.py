import asyncio
import secrets
from contextlib import asynccontextmanager, suppress

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message, User
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.ai import (
    format_admin_usage_summary,
    generate_report_content,
    get_aitunnel_balance,
)
from services.generation_progress import (
    TaskProgress,
    active_fraction,
    displayed_percent,
    format_progress_percent,
)
from services.astro import (
    calculate_chart,
    geocode,
    is_approximate_time,
    parse_date,
    parse_time,
)
from config.settings import settings
from database.repository import (
    AI_MODEL_ROLE_LABELS,
    DEFAULT_AI_MODELS,
    DEFAULT_GENDER,
    DEFAULT_REPORT_PRICES,
    GENDER_FEMALE,
    GENDER_MALE,
    birth_fingerprint,
    complete_order,
    create_order,
    get_ai_model,
    get_ai_models,
    get_free_daily_limit_enabled,
    get_free_generation,
    get_order,
    get_profile,
    get_app_setting,
    get_report_context,
    get_report_price,
    get_report_prices,
    get_test_mode,
    gender_label_ru,
    gender_symbol,
    has_used_free_today,
    mark_free_used_today,
    normalize_gender,
    save_free_generation,
    save_profile,
    save_report_context,
    set_ai_model,
    set_free_daily_limit_enabled,
    set_order_status,
    set_app_setting,
    set_report_price,
    set_test_mode,
)
from services.reports_new import generate_report

router = Router()
PRICES = DEFAULT_REPORT_PRICES
NAMES = {
    "personality": "Разбор личности",
    "love": "Любовь и отношения",
    "compatibility": "Совместимость",
    "money": "Деньги и реализация",
}
PENDING_REPORTS: dict[int, tuple[dict, dict | None]] = {}
MAX_PENDING_FREE_REPORTS_PER_USER = 8
PENDING_FREE_REPORTS: dict[str, dict] = {}
PENDING_FREE_REPORT_IDS_BY_USER: dict[int, list[str]] = {}
_REPORT_GUARD = asyncio.Lock()
_REPORT_IN_PROGRESS: set[int] = set()
FREE_REPORT_TYPES = {
    "personality": "personality_free",
    "love": "love_free",
    "compatibility": "compatibility_free",
    "money": "money_free",
}
FREE_UPSELL_TEXTS = {
    "personality": (
        "Вы уже увидели верхний слой профиля — как вы устроены, как вас считывают "
        "и где ваши сильные и уязвимые точки.\n\n"
        "Полный PDF по личности идёт дальше и собирает цельную карту:\n"
        "• внутренний мир, мышление, эмоции и стресс;\n"
        "• сильные, сложные и скрытые качества;\n"
        "• любовь, повторяющиеся сценарии и тип подходящего партнёра;\n"
        "• денежный профиль, карьера и профессиональные направления;\n"
        "• главные блоки, точки роста и практические рекомендации;\n"
        "• итоговый профиль, который связывает всё в одну картину.\n\n"
        "Это не «ещё один гороскоп», а подробный разбор, который помогает узнать себя "
        "и понять, что менять в первую очередь."
    ),
    "love": (
        "В мини-разборе уже видно, как вы влюбляетесь, что притягивает и что "
        "может разрушать отношения.\n\n"
        "Полный любовный PDF раскрывает механику близости целиком:\n"
        "• как вы проявляете любовь и как хотите её получать;\n"
        "• недоверие, ревность и реакция на дистанцию;\n"
        "• стиль конфликтов и то, что трудно сказать партнёру;\n"
        "• расставания, возвращение к прошлому и повторяющиеся сценарии;\n"
        "• какой партнёр подходит, с кем может быть сложно;\n"
        "• что усиливает отношения и итоговый любовный портрет.\n\n"
        "Так проще увидеть не только «какой вы в любви», но и где отношения "
        "ломаются — и как это можно изменить."
    ),
    "compatibility": (
        "Мини-разбор пары показал эмоциональный тон, притяжение и главные зоны "
        "напряжения.\n\n"
        "Полный PDF совместимости разбирает динамику в деталях:\n"
        "• общение, доверие, ревность и личные границы;\n"
        "• конфликты и что одного притягивает / раздражает в другом;\n"
        "• что каждому нужно от партнёра;\n"
        "• сильные и сложные стороны пары;\n"
        "• повторяющиеся сценарии;\n"
        "• как вам лучше общаться и как улучшить отношения;\n"
        "• итоговый портрет пары.\n\n"
        "Это помогает понять не «судьбу», а реальную механику вашей связи — "
        "где вы усиливаете друг друга и где спотыкаетесь."
    ),
    "money": (
        "В мини-разборе уже намечены отношение к деньгам, мотивация и направления, "
        "которые вам ближе.\n\n"
        "Полный денежный PDF собирает рабочий и финансовый профиль:\n"
        "• стабильность, риск, ответственность и работа в команде;\n"
        "• предпринимательский потенциал и качества, которые можно монетизировать;\n"
        "• подходящий формат и среда работы;\n"
        "• риск выгорания и навыки для развития;\n"
        "• направления, почему они подходят и что мешает реализации;\n"
        "• главная точка роста и итоговый денежный профиль.\n\n"
        "Так проще выбрать, куда вкладывать силы, а не гадать «в чём мой талант»."
    ),
}
PAID_OFFER_TEXTS = {
    "personality": (
        "Полный разбор личности по вашим данным рождения.\n\n"
        "В PDF — психологический портрет, внутренний мир, сильные и скрытые качества, "
        "любовь и сценарии, деньги и карьера, блоки, точки роста и практические "
        "рекомендации. Всё собирается в один итоговый профиль."
    ),
    "love": (
        "Полный любовный разбор по вашим данным рождения.\n\n"
        "В PDF — влюблённость и притяжение, как вы даёте и хотите получать любовь, "
        "ревность и дистанция, конфликты, сценарии отношений, подходящий партнёр "
        "и итоговый любовный портрет."
    ),
    "compatibility": (
        "Полный разбор совместимости по данным вашей пары.\n\n"
        "В PDF — динамика, общение, доверие, границы, конфликты, что притягивает "
        "и раздражает, потребности каждого, сценарии пары и способы улучшить отношения."
    ),
    "money": (
        "Полный денежный разбор по вашим данным рождения.\n\n"
        "В PDF — отношение к деньгам и риску, предпринимательский потенциал, "
        "формат работы, направления для монетизации, блоки, навыки роста "
        "и итоговый денежный профиль."
    ),
}
REPORT_PROGRESS_TEXT = "🔮 Формирую ваш персональный результат"
SCENARIO_INTROS = {
    "personality": (
        "🧠 РАЗБОР ЛИЧНОСТИ\n\n"
        "Подготовлю персональный разбор по вашим данным рождения. "
        "Полный PDF раскроет личность, отношения, деньги и точки роста."
    ),
    "love": (
        "❤️ ЛЮБОВЬ И ОТНОШЕНИЯ\n\n"
        "Подготовлю персональный любовный разбор по вашим данным рождения. "
        "Полный PDF раскроет близость, конфликты, сценарии и портрет в отношениях."
    ),
    "compatibility": (
        "💑 СОВМЕСТИМОСТЬ\n\n"
        "Подготовлю разбор совместимости по данным вашей пары. "
        "Полный PDF раскроет динамику, доверие, границы и конфликты.\n\n"
        "Для анализа понадобятся данные вас и партнёра."
    ),
    "money": (
        "💰 ДЕНЬГИ И РЕАЛИЗАЦИЯ\n\n"
        "Подготовлю персональный денежный разбор по вашим данным рождения. "
        "Полный PDF раскроет деньги, карьеру, навыки и точки роста."
    ),
}


class BirthStates(StatesGroup):
    own_gender = State()
    own_date = State()
    own_time = State()
    own_place = State()
    partner_date = State()
    partner_time = State()
    partner_place = State()


class AdminStates(StatesGroup):
    support_text = State()
    share_text = State()
    main_menu_text = State()
    price_value = State()
    model_value = State()


async def menu(user_id: int):
    share_text = await get_app_setting("share_text") or "Узнай себя по звёздам →"
    has_profile = await get_profile(user_id) is not None
    builder = InlineKeyboardBuilder()
    builder.button(text="🧠 Личность", callback_data="scenario:personality")
    builder.button(text="❤️ Любовь и отношения", callback_data="scenario:love")
    builder.button(text="💰 Деньги и реализация", callback_data="scenario:money")
    builder.button(text="💑 Совместимость", callback_data="scenario:compatibility")
    builder.button(text="📤 Поделиться", switch_inline_query=share_text)
    if has_profile:
        builder.button(text="✏️ Изменить данные", callback_data="edit_profile")
    builder.button(text="📖 Инструкция", callback_data="help")
    builder.button(text="🆘 Поддержка", callback_data="support")
    builder.adjust(1)
    return builder.as_markup()


async def get_main_menu_text() -> str:
    return await get_app_setting("main_menu_text") or (
        "🔮 <b>Узнай о себе больше, чем может рассказать обычный гороскоп</b>\n\n"
        "Этот разбор создаётся индивидуально по вашим данным рождения — "
        "дате, времени и месту.\n\n"
        "Здесь вы можете узнать:\n"
        "🧠 какой вы человек на самом деле\n"
        "❤️ как вы любите и кого выбираете\n"
        "💰 где раскрывается ваш потенциал реализации\n"
        "💑 что происходит между вами и конкретным человеком\n\n"
        "Выберите, что вам интересно 👇"
    )


def back_keyboard(destination: str, text: str = "⬅️ Назад"):
    builder = InlineKeyboardBuilder()
    builder.button(text=text, callback_data=f"back:{destination}")
    return builder.as_markup()


def back_to_menu():
    return back_keyboard("menu")


def back_to_edit_profile():
    return back_keyboard("edit_profile")


def back_to_admin_gens():
    return back_keyboard("admin_gens")


def flow_back_keyboard(*, admin_mode: bool):
    return back_to_admin_gens() if admin_mode else back_to_menu()


async def _try_begin_report(user_id: int) -> bool:
    async with _REPORT_GUARD:
        if user_id in _REPORT_IN_PROGRESS:
            return False
        _REPORT_IN_PROGRESS.add(user_id)
        return True


async def _end_report(user_id: int) -> None:
    async with _REPORT_GUARD:
        _REPORT_IN_PROGRESS.discard(user_id)


async def _clear_callback_keyboard(callback: CallbackQuery) -> None:
    with suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)


def pdf_offer_keyboard(
    scenario_name: str,
    *,
    admin_mode: bool = False,
    price: int | None = None,
):
    builder = InlineKeyboardBuilder()
    if admin_mode:
        builder.button(
            text="📄 Сформировать полный PDF",
            callback_data=f"admin_buy:{scenario_name}",
        )
        builder.button(text="⬅️ К генерациям", callback_data="admin:generations")
    else:
        amount = price if price is not None else PRICES[scenario_name]
        builder.button(
            text=f"🔓 Получить полный PDF · {amount}⭐",
            callback_data=f"buy:{scenario_name}",
        )
        builder.button(text="⬅️ Назад", callback_data="back:menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_generations_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="🧠 Личность", callback_data="admin_scenario:personality")
    builder.button(text="❤️ Любовь и отношения", callback_data="admin_scenario:love")
    builder.button(text="💰 Деньги и реализация", callback_data="admin_scenario:money")
    builder.button(text="💑 Совместимость", callback_data="admin_scenario:compatibility")
    builder.button(text="⬅️ В админку", callback_data="admin:back")
    builder.adjust(1)
    return builder.as_markup()


def admin_generations_text() -> str:
    return (
        "Админ-генерации\n\n"
        "Тот же набор разборов, что у пользователя, но без Stars и без дневного "
        "лимита бесплатных.\n"
        "Можно проверить бесплатный мини-разбор и сразу собрать полный PDF."
    )


def store_pending_free_report(
    user_id: int,
    scenario_name: str,
    sections: list[dict[str, str]],
    *,
    admin_mode: bool = False,
) -> str:
    report_id = secrets.token_hex(4)
    PENDING_FREE_REPORTS[report_id] = {
        "id": report_id,
        "user_id": user_id,
        "scenario": scenario_name,
        "sections": sections,
        "admin_mode": admin_mode,
    }
    ids = PENDING_FREE_REPORT_IDS_BY_USER.setdefault(user_id, [])
    ids.append(report_id)
    while len(ids) > MAX_PENDING_FREE_REPORTS_PER_USER:
        PENDING_FREE_REPORTS.pop(ids.pop(0), None)
    return report_id


def get_pending_free_report(user_id: int, report_id: str) -> dict | None:
    record = PENDING_FREE_REPORTS.get(report_id)
    if not record or record["user_id"] != user_id:
        return None
    return record


def parse_free_section_callback(data: str) -> tuple[str | None, int] | None:
    if not data.startswith("free_section:"):
        return None
    parts = data.split(":")
    try:
        if len(parts) == 2:
            return None, int(parts[1])
        if len(parts) == 3 and parts[1]:
            return parts[1], int(parts[2])
    except ValueError:
        return None
    return None


def resolve_pending_free_report(user_id: int, report_id: str | None) -> dict | None:
    if report_id:
        return get_pending_free_report(user_id, report_id)
    ids = PENDING_FREE_REPORT_IDS_BY_USER.get(user_id) or []
    if not ids:
        return None
    return get_pending_free_report(user_id, ids[-1])


def free_section_keyboard(title: str, report_id: str, section_index: int):
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Посмотреть раздел «{title}»",
        callback_data=f"free_section:{report_id}:{section_index}",
    )
    return builder.as_markup()


def edit_profile_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="♀♂ Пол", callback_data="edit:gender")
    builder.button(text="📅 Дата рождения", callback_data="edit:date")
    builder.button(text="🕐 Время рождения", callback_data="edit:time")
    builder.button(text="📍 Место рождения", callback_data="edit:place")
    builder.button(text="⬅️ Назад", callback_data="back:menu")
    builder.adjust(1)
    return builder.as_markup()


def gender_keyboard(*, back_destination: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="♀", callback_data=f"gender:{GENDER_FEMALE}")
    builder.button(text="♂", callback_data=f"gender:{GENDER_MALE}")
    builder.button(text="⬅️ Назад", callback_data=f"back:{back_destination}")
    builder.adjust(2, 1)
    return builder.as_markup()


def format_gender_line(gender: str | None) -> str:
    value = normalize_gender(gender or DEFAULT_GENDER)
    return f"{gender_symbol(value)} Пол: {gender_label_ru(value)}"


def unknown_time_keyboard(back_destination: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🕐 Не знаю точное время", callback_data="time_unknown")
    builder.button(text="⬅️ Назад", callback_data=f"back:{back_destination}")
    builder.adjust(1)
    return builder.as_markup()


def admin_menu(*, test_mode: bool, free_daily_limit: bool):
    builder = InlineKeyboardBuilder()
    test_label = "🟢 Тестовый режим: ВКЛ" if test_mode else "⚪ Тестовый режим: ВЫКЛ"
    limit_label = (
        "🟢 Лимит бесплатных: ВКЛ"
        if free_daily_limit
        else "⚪ Лимит бесплатных: ВЫКЛ"
    )
    builder.button(text=test_label, callback_data="admin:test_toggle")
    builder.button(text=limit_label, callback_data="admin:free_daily_limit_toggle")
    builder.button(text="🧪 Генерации", callback_data="admin:generations")
    builder.button(text="💰 Цены", callback_data="admin:prices")
    builder.button(text="🤖 Модели", callback_data="admin:models")
    builder.button(text="📝 Настройки текстов", callback_data="admin:texts")
    builder.adjust(1)
    return builder.as_markup()


async def models_settings_menu():
    models = await get_ai_models()
    builder = InlineKeyboardBuilder()
    for role in ("free", "expensive", "cheap"):
        builder.button(
            text=f"{AI_MODEL_ROLE_LABELS[role]}",
            callback_data=f"admin:model:{role}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin:back")
    builder.adjust(1)
    return builder.as_markup()


def models_settings_message(models: dict[str, str] | None = None) -> str:
    lines = [
        "Управление моделями",
        "",
        "• Бесплатные — готовый текст мини-отчёта волнами",
        "• Дорогая — скелет разделов PDF (2–3 пункта) и короткая задумка",
        "• Дешёвая — готовый текст каждого раздела PDF по скелету",
        "",
        "Выберите роль, чтобы сменить id модели AITUNNEL.",
    ]
    if models:
        lines.append("")
        for role in ("free", "expensive", "cheap"):
            lines.append(f"• {AI_MODEL_ROLE_LABELS[role]}: {models[role]}")
    return "\n".join(lines)


async def prices_settings_menu():
    prices = await get_report_prices()
    builder = InlineKeyboardBuilder()
    for scenario in ("personality", "love", "money", "compatibility"):
        builder.button(
            text=f"{NAMES[scenario]} · {prices[scenario]}⭐",
            callback_data=f"admin:price:{scenario}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin:back")
    builder.adjust(1)
    return builder.as_markup()


def prices_settings_message(prices: dict[str, int] | None = None) -> str:
    lines = [
        "Настройка цен генерации",
        "",
        "Цены в Telegram Stars за полный PDF.",
        "Выберите сценарий, чтобы изменить цену.",
    ]
    if prices:
        lines.append("")
        for scenario in ("personality", "love", "money", "compatibility"):
            lines.append(f"• {NAMES[scenario]}: {prices[scenario]}⭐")
    return "\n".join(lines)


def text_settings_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Описание главного меню", callback_data="admin:main_menu_text")
    builder.button(text="🆘 Текст поддержки", callback_data="admin:support_text")
    builder.button(text="📤 Текст «Поделиться»", callback_data="admin:share_text")
    builder.button(text="⬅️ Назад", callback_data="admin:back")
    builder.adjust(1)
    return builder.as_markup()


def text_settings_message() -> str:
    return (
        "Настройки текстов\n\n"
        "Выберите, какой текст изменить.\n"
        "Для описания главного меню поддерживается Telegram HTML-разметка: "
        "<b>жирный</b>, <i>курсив</i>, <a href=\"https://example.com\">ссылка</a>."
    )


def admin_text(
    *,
    test_mode: bool,
    free_daily_limit: bool,
    balance_data: dict[str, float] | None,
) -> str:
    test_label = "ВКЛ" if test_mode else "ВЫКЛ"
    limit_label = "ВКЛ" if free_daily_limit else "ВЫКЛ"
    if balance_data is None:
        balance = "недоступен — проверьте ключ AITUNNEL и подключение"
    else:
        balance = f"{balance_data['balance']:.2f} ₽"
    return (
        "Панель администратора\n\n"
        f"Баланс AITUNNEL: {balance}\n"
        f"Тестовый режим: {test_label}\n"
        f"Лимит бесплатных: {limit_label}\n\n"
        "В тестовом режиме реальные Telegram Stars не списываются: "
        "после нажатия кнопки покупки PDF формируется сразу.\n\n"
        "Лимит бесплатных: не больше одного бесплатного мини-разбора в сутки "
        "на пользователя. При исчерпании лимита остаётся кнопка полного PDF.\n\n"
        "Раздел «Генерации» — проверка разборов без оплаты и без лимита.\n"
        "Раздел «Цены» — стоимость полного PDF в Stars.\n"
        "Раздел «Модели» — дорогая модель для скелета и дешёвая для текста разделов."
    )


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def send_admin_usage_summary(message: Message, content: dict | None) -> None:
    summary = format_admin_usage_summary((content or {}).get("usage"))
    if not summary:
        return
    await message.answer(summary)


async def _edit_or_answer(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str | None = None,
) -> None:
    """Edit message text when possible; otherwise send a new message.

    Needed when the callback sits on a document/photo (PDF) that has no text body.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def _refresh_admin_panel(message: Message, *, answer_text: str | None = None):
    test_mode = await get_test_mode()
    free_daily_limit = await get_free_daily_limit_enabled()
    balance = await get_aitunnel_balance()
    text = admin_text(
        test_mode=test_mode,
        free_daily_limit=free_daily_limit,
        balance_data=balance,
    )
    markup = admin_menu(test_mode=test_mode, free_daily_limit=free_daily_limit)
    if answer_text is None:
        await _edit_or_answer(message, text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


@router.message(Command("admin"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Команда доступна только администраторам.")
        return
    await _refresh_admin_panel(message, answer_text="ok")


@router.callback_query(F.data == "admin:test_toggle")
async def toggle_test_mode(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    enabled = not await get_test_mode()
    await set_test_mode(enabled)
    await callback.answer("Тестовый режим включён" if enabled else "Тестовый режим выключен")
    await _refresh_admin_panel(callback.message)


@router.callback_query(F.data == "admin:free_daily_limit_toggle")
async def toggle_free_daily_limit(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    enabled = not await get_free_daily_limit_enabled()
    await set_free_daily_limit_enabled(enabled)
    await callback.answer(
        "Лимит бесплатных включён" if enabled else "Лимит бесплатных выключен"
    )
    await _refresh_admin_panel(callback.message)


@router.callback_query(F.data == "admin:prices")
async def open_prices_settings(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    prices = await get_report_prices()
    await _edit_or_answer(
        callback.message,
        prices_settings_message(prices),
        reply_markup=await prices_settings_menu(),
    )


@router.callback_query(F.data.startswith("admin:price:"))
async def edit_report_price(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    scenario_name = callback.data.rsplit(":", 1)[-1]
    if scenario_name not in PRICES:
        await callback.answer("Этот сценарий пока недоступен.", show_alert=True)
        return
    current = await get_report_price(scenario_name)
    await callback.answer()
    await state.set_state(AdminStates.price_value)
    await state.update_data(price_scenario=scenario_name)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin:cancel_price_edit")
    await callback.message.answer(
        f"Текущая цена «{NAMES[scenario_name]}»: {current}⭐\n\n"
        "Отправьте новую цену целым числом Stars (минимум 1).",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "admin:cancel_price_edit")
async def cancel_price_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Изменение отменено")
    prices = await get_report_prices()
    await callback.message.answer(
        prices_settings_message(prices),
        reply_markup=await prices_settings_menu(),
    )


@router.message(AdminStates.price_value)
async def save_report_price_value(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Команда доступна только администраторам.")
        return
    data = await state.get_data()
    scenario_name = data.get("price_scenario")
    if scenario_name not in PRICES:
        await state.clear()
        await message.answer("Сценарий не выбран. Откройте настройку цен заново.")
        return
    raw = (message.text or "").strip().replace("⭐", "").replace(" ", "")
    try:
        amount = int(raw)
    except ValueError:
        await message.answer("Нужно целое число Stars, например 399. Попробуйте ещё раз.")
        return
    if amount < 1:
        await message.answer("Цена должна быть не меньше 1⭐. Попробуйте ещё раз.")
        return
    await set_report_price(scenario_name, amount)
    await state.clear()
    await message.answer(
        f"Цена «{NAMES[scenario_name]}» обновлена: {amount}⭐ ✅",
        reply_markup=back_keyboard("prices"),
    )


@router.callback_query(F.data == "admin:models")
async def open_models_settings(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    models = await get_ai_models()
    await _edit_or_answer(
        callback.message,
        models_settings_message(models),
        reply_markup=await models_settings_menu(),
    )


@router.callback_query(F.data.startswith("admin:model:"))
async def edit_ai_model(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    role = callback.data.rsplit(":", 1)[-1]
    if role not in DEFAULT_AI_MODELS:
        await callback.answer("Неизвестная роль модели.", show_alert=True)
        return
    current = await get_ai_model(role)
    await callback.answer()
    await state.set_state(AdminStates.model_value)
    await state.update_data(model_role=role)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin:cancel_model_edit")
    await callback.message.answer(
        f"{AI_MODEL_ROLE_LABELS[role]}\n"
        f"Сейчас: {current}\n\n"
        "Отправьте id модели AITUNNEL, например deepseek-v4-flash.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "admin:cancel_model_edit")
async def cancel_model_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Изменение отменено")
    models = await get_ai_models()
    await callback.message.answer(
        models_settings_message(models),
        reply_markup=await models_settings_menu(),
    )


@router.message(AdminStates.model_value)
async def save_ai_model_value(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Команда доступна только администраторам.")
        return
    data = await state.get_data()
    role = data.get("model_role")
    if role not in DEFAULT_AI_MODELS:
        await state.clear()
        await message.answer("Роль не выбрана. Откройте настройку моделей заново.")
        return
    model_name = (message.text or "").strip().strip("`")
    if not model_name or any(ch.isspace() for ch in model_name):
        await message.answer(
            "Нужен id модели без пробелов, например deepseek-v4-flash. "
            "Попробуйте ещё раз."
        )
        return
    await set_ai_model(role, model_name)
    await state.clear()
    await message.answer(
        f"{AI_MODEL_ROLE_LABELS[role]} обновлена: {model_name} ✅",
        reply_markup=back_keyboard("models"),
    )


@router.callback_query(F.data == "admin:texts")
async def open_text_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await _edit_or_answer(
        callback.message,
        text_settings_message(),
        reply_markup=text_settings_menu(),
    )


@router.callback_query(F.data == "admin:back")
async def back_to_admin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await _refresh_admin_panel(callback.message, answer_text="ok")


@router.callback_query(F.data == "admin:generations")
async def open_admin_generations(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        admin_generations_text(),
        reply_markup=admin_generations_menu(),
    )


@router.callback_query(F.data.startswith("admin_scenario:"))
async def admin_scenario(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    scenario_name = callback.data.split(":", 1)[1]
    if scenario_name not in PRICES:
        await callback.answer("Этот сценарий пока недоступен.", show_alert=True)
        return
    await callback.answer()
    await ask_own_data(
        callback.message,
        state,
        scenario_name,
        callback.from_user.id,
        admin_mode=True,
    )


@router.callback_query(F.data.startswith("back:"))
async def navigate_back(callback: CallbackQuery, state: FSMContext):
    destination = callback.data.split(":", 1)[1]
    await state.clear()
    await callback.answer()
    if destination == "menu":
        await callback.message.answer(
            await get_main_menu_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=await menu(callback.from_user.id),
        )
    elif destination == "admin_gens" and is_admin(callback.from_user.id):
        await callback.message.answer(
            admin_generations_text(),
            reply_markup=admin_generations_menu(),
        )
    elif destination == "edit_profile":
        await start_edit(callback.message, state, callback.from_user.id)
    elif destination == "text_settings" and is_admin(callback.from_user.id):
        await callback.message.answer(text_settings_message(), reply_markup=text_settings_menu())
    elif destination == "prices" and is_admin(callback.from_user.id):
        prices = await get_report_prices()
        await callback.message.answer(
            prices_settings_message(prices),
            reply_markup=await prices_settings_menu(),
        )
    elif destination == "models" and is_admin(callback.from_user.id):
        models = await get_ai_models()
        await callback.message.answer(
            models_settings_message(models),
            reply_markup=await models_settings_menu(),
        )


@router.callback_query(F.data == "admin:support_text")
async def edit_support_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.support_text)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin:cancel_support_edit")
    await callback.message.answer(
        "Отправьте новый текст поддержки.\n"
        "Можно добавить ссылку, Telegram username и переносы строк.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "admin:main_menu_text")
async def edit_main_menu_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.main_menu_text)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin:cancel_main_menu_edit")
    await callback.message.answer(
        "Отправьте новое описание главного меню.\n"
        "Можно использовать Telegram HTML: <b>жирный</b>, <i>курсив</i>, "
        "<a href=\"https://example.com\">ссылка</a>.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "admin:cancel_main_menu_edit")
async def cancel_main_menu_text_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Изменение отменено")
    await callback.message.answer(
        text_settings_message(),
        reply_markup=text_settings_menu(),
    )


@router.message(AdminStates.main_menu_text)
async def save_main_menu_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Команда доступна только администраторам.")
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Описание не должно быть пустым. Попробуйте ещё раз.")
        return
    await set_app_setting("main_menu_text", text)
    await state.clear()
    await message.answer(
        "Описание главного меню обновлено ✅",
        reply_markup=back_keyboard("text_settings"),
    )


@router.callback_query(F.data == "admin:share_text")
async def edit_share_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.share_text)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin:cancel_share_edit")
    await callback.message.answer(
        "Отправьте текст, который будет подставляться при нажатии «Поделиться».",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "admin:cancel_share_edit")
async def cancel_share_text_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Изменение отменено")
    await callback.message.answer(
        text_settings_message(),
        reply_markup=text_settings_menu(),
    )


@router.message(AdminStates.share_text)
async def save_share_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Команда доступна только администраторам.")
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст не должен быть пустым. Попробуйте ещё раз.")
        return
    await set_app_setting("share_text", text)
    await state.clear()
    await message.answer(
        "Текст «Поделиться» обновлён ✅",
        reply_markup=back_keyboard("text_settings"),
    )


@router.callback_query(F.data == "admin:cancel_support_edit")
async def cancel_support_text_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Изменение отменено")
    await callback.message.answer(
        text_settings_message(),
        reply_markup=text_settings_menu(),
    )


@router.message(AdminStates.support_text)
async def save_support_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Команда доступна только администраторам.")
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст не должен быть пустым. Попробуйте ещё раз.")
        return
    await set_app_setting("support_text", text)
    await state.clear()
    await message.answer(
        "Текст поддержки обновлён ✅",
        reply_markup=back_keyboard("text_settings"),
    )


@router.message(Command("start"))
async def start(message: Message):
    await message.answer(
        await get_main_menu_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=await menu(message.from_user.id),
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await send_help(message)


async def send_help(message: Message):
    await message.answer(
        "Выберите, что хочется узнать о себе прямо сейчас ✨\n\n"
        "🧠 Личность — ваши сильные стороны, внутренние противоречия и точки роста.\n\n"
        "❤️ Любовь и отношения — как вы проявляете чувства и кого выбираете.\n\n"
        "💰 Деньги и реализация — ваши рабочие опоры и направления развития.\n\n"
        "💑 Совместимость — что объединяет вас с партнёром и где нужны договорённости.\n\n"
        "✨ Полный разбор — все ключевые темы в одном персональном профиле.\n\n"
        "📤 Поделиться — отправьте бота близкому человеку и вместе откройте "
        "подсказки звёзд.\n\n"
        "✏️ Изменить данные — обновите дату, время или место рождения для "
        "максимально точного разбора.\n\n"
        "📖 Инструкция — вернитесь к этому описанию в любой момент.\n\n"
        "🆘 Поддержка — мы рядом, если появятся вопросы.",
        reply_markup=back_to_menu(),
    )


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery):
    await callback.answer()
    await send_help(callback.message)


@router.message(Command("support"))
async def support(message: Message):
    text = await get_app_setting("support_text")
    await message.answer(text or f"По вопросам: {settings.support_url}", reply_markup=back_to_menu())


@router.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery):
    await callback.answer()
    await support(callback.message)


@router.message(Command("profile"))
async def profile(message: Message, state: FSMContext):
    data = await get_profile(message.from_user.id)
    if not data:
        await start_edit(message, state, message.from_user.id)
        return
    await message.answer(
        f"Ваш профиль:\n"
        f"{format_gender_line(data.get('gender'))}\n"
        f"📅 {data['birth_date'][8:10]}.{data['birth_date'][5:7]}.{data['birth_date'][:4]}\n"
        f"🕐 {data['birth_time']}\n📍 {data['birth_place']}\n\n/edit — изменить",
        reply_markup=back_to_menu(),
    )


@router.message(Command("edit"))
async def edit(message: Message, state: FSMContext):
    await start_edit(message, state, message.from_user.id)


async def start_edit(message: Message, state: FSMContext, user_id: int):
    await state.clear()
    profile = await get_profile(user_id)
    if not profile:
        await state.set_state(BirthStates.own_gender)
        await state.update_data(next_scenario="profile")
        await message.answer(
            "♀♂ ШАГ 1 ИЗ 4\n\n"
            "Выберите пол — это нужно для корректного обращения в разборе.\n"
            "♀ — женский, ♂ — мужской.",
            reply_markup=gender_keyboard(back_destination="menu"),
        )
        return
    await message.answer(
        "Ваши текущие данные:\n\n"
        f"{format_gender_line(profile.get('gender'))}\n"
        f"📅 Дата рождения: {profile['birth_date'][8:10]}."
        f"{profile['birth_date'][5:7]}.{profile['birth_date'][:4]}\n"
        f"🕐 Время рождения: {profile['birth_time']}\n"
        f"📍 Место рождения: {profile['birth_place']}\n\n"
        "Что хотите изменить?",
        reply_markup=edit_profile_menu(),
    )


@router.callback_query(F.data == "edit_profile")
async def edit_profile_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_edit(callback.message, state, callback.from_user.id)


@router.callback_query(F.data.startswith("edit:"))
async def choose_profile_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":", 1)[1]
    await state.clear()
    await state.update_data(edit_field=field)
    await callback.answer()
    if field == "gender":
        await state.set_state(BirthStates.own_gender)
        await callback.message.answer(
            "Выберите пол:\n♀ — женский, ♂ — мужской.",
            reply_markup=gender_keyboard(back_destination="edit_profile"),
        )
    elif field == "date":
        await state.set_state(BirthStates.own_date)
        await callback.message.answer(
            "Введите дату рождения в формате ДД.ММ.ГГГГ:",
            reply_markup=back_to_edit_profile(),
        )
    elif field == "time":
        await state.set_state(BirthStates.own_time)
        await callback.message.answer(
            "Введите время рождения ЧЧ:ММ или выберите вариант ниже:",
            reply_markup=unknown_time_keyboard("edit_profile"),
        )
    elif field == "place":
        await state.set_state(BirthStates.own_place)
        await callback.message.answer(
            "Введите город и страну рождения:",
            reply_markup=back_to_edit_profile(),
        )


@router.callback_query(F.data.startswith("gender:"))
async def choose_gender(callback: CallbackQuery, state: FSMContext):
    raw = callback.data.split(":", 1)[1]
    if raw not in {GENDER_FEMALE, GENDER_MALE}:
        await callback.answer("Выберите ♀ или ♂", show_alert=True)
        return
    gender = normalize_gender(raw)
    data = await state.get_data()
    await callback.answer()
    with suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)

    if data.get("edit_field") == "gender":
        profile = await get_profile(callback.from_user.id)
        if not profile:
            await state.clear()
            await state.set_state(BirthStates.own_gender)
            await state.update_data(next_scenario="profile")
            await callback.message.answer(
                "♀♂ ШАГ 1 ИЗ 4\n\n"
                "Сначала заполните профиль. Выберите пол:\n"
                "♀ — женский, ♂ — мужской.",
                reply_markup=gender_keyboard(back_destination="menu"),
            )
            return
        profile["gender"] = gender
        await save_profile(callback.from_user.id, profile)
        await state.clear()
        await callback.message.answer(
            f"Данные сохранены ✅\n{format_gender_line(gender)}",
            reply_markup=back_to_edit_profile(),
        )
        return

    await state.update_data(own_gender=gender)
    await state.set_state(BirthStates.own_date)
    admin_mode = bool(data.get("admin_generation"))
    if data.get("next_scenario") == "profile":
        markup = back_keyboard("menu")
    else:
        markup = flow_back_keyboard(admin_mode=admin_mode)
    await callback.message.answer(
        "📅 ШАГ 2 ИЗ 4\n\n"
        "Напишите дату своего рождения.\n"
        "Например: 24.07.1998",
        reply_markup=markup,
    )


async def save_profile_field(message: Message, field: str, value: str, state: FSMContext) -> None:
    profile = await get_profile(message.from_user.id)
    if not profile:
        await state.clear()
        await state.set_state(BirthStates.own_gender)
        await state.update_data(next_scenario="profile")
        await message.answer(
            "♀♂ ШАГ 1 ИЗ 4\n\n"
            "Выберите пол — это нужно для корректного обращения в разборе.\n"
            "♀ — женский, ♂ — мужской.",
            reply_markup=gender_keyboard(back_destination="menu"),
        )
        return
    profile[field] = value
    await save_profile(message.from_user.id, profile)
    await message.answer("Данные сохранены ✅", reply_markup=back_to_edit_profile())


async def ask_own_data(
    message: Message,
    state: FSMContext,
    scenario: str,
    user_id: int,
    *,
    admin_mode: bool = False,
):
    await message.answer(SCENARIO_INTROS[scenario])
    profile = await get_profile(user_id)
    if profile and scenario == "compatibility":
        own_chart = calculate_chart(
            profile["birth_date"],
            profile["birth_time"],
            profile["latitude"],
            profile["longitude"],
            time_is_approximate=bool(profile["time_is_approximate"]),
        )
        await state.clear()
        await state.update_data(
            own_chart=own_chart,
            next_scenario=scenario,
            admin_generation=admin_mode,
        )
        await state.set_state(BirthStates.partner_date)
        await message.answer(
            "Ваши данные уже сохранены ✅\n\n"
            "Теперь нужны данные второго человека.\n\n"
            "📅 Дата рождения партнёра\n"
            "Например: 24.07.1998",
            reply_markup=flow_back_keyboard(admin_mode=admin_mode),
        )
        return
    if profile:
        chart = calculate_chart(
            profile["birth_date"],
            profile["birth_time"],
            profile["latitude"],
            profile["longitude"],
            time_is_approximate=bool(profile["time_is_approximate"]),
        )
        await show_teaser(
            message,
            scenario,
            chart,
            user_id=user_id,
            admin_mode=admin_mode,
        )
        return
    await state.clear()
    await state.set_state(BirthStates.own_gender)
    await state.update_data(next_scenario=scenario, admin_generation=admin_mode)
    await message.answer(
        "♀♂ ШАГ 1 ИЗ 4\n\n"
        "Выберите пол — это нужно для корректного обращения в разборе.\n"
        "♀ — женский, ♂ — мужской.",
        reply_markup=gender_keyboard(
            back_destination="admin_gens" if admin_mode else "menu"
        ),
    )


@router.callback_query(F.data.startswith("scenario:"))
async def scenario(callback: CallbackQuery, state: FSMContext):
    scenario_name = callback.data.split(":", 1)[1]
    if scenario_name not in PRICES:
        await callback.answer("Этот сценарий пока недоступен.", show_alert=True)
        return
    await callback.answer()
    await ask_own_data(callback.message, state, scenario_name, callback.from_user.id)


@router.message(BirthStates.own_date)
async def own_date(message: Message, state: FSMContext):
    try:
        value = parse_date(message.text)
    except (ValueError, TypeError):
        await message.answer("Не понял дату. Используйте формат ДД.ММ.ГГГГ, например 21.03.1990.")
        return
    data = await state.get_data()
    if data.get("edit_field") == "date":
        await save_profile_field(message, "birth_date", value, state)
        await state.clear()
        return
    await state.update_data(own_date=value)
    await state.set_state(BirthStates.own_time)
    back_destination = "admin_gens" if data.get("admin_generation") else "menu"
    await message.answer(
        "🕐 ШАГ 3 ИЗ 4\n\n"
        "Теперь напишите время рождения.\n"
        "Например: 14:35\n\n"
        "Чем точнее время, тем персональнее получится разбор.",
        reply_markup=unknown_time_keyboard(back_destination),
    )


@router.message(BirthStates.own_time)
async def own_time(
    message: Message,
    state: FSMContext,
    time_text: str | None = None,
    user_id: int | None = None,
):
    try:
        value = parse_time(time_text if time_text is not None else message.text)
    except (ValueError, TypeError):
        await message.answer("Нужно время в формате ЧЧ:ММ, например 14:30, или «не знаю».")
        return
    user_id = user_id or message.from_user.id
    data = await state.get_data()
    if data.get("edit_field") == "time":
        profile = await get_profile(user_id)
        if profile:
            profile["birth_time"] = value
            profile["time_is_approximate"] = is_approximate_time(
                time_text if time_text is not None else message.text
            )
            await save_profile(user_id, profile)
            await message.answer("Данные сохранены ✅", reply_markup=back_to_edit_profile())
        else:
            await save_profile_field(message, "birth_time", value, state)
        await state.clear()
        return
    await state.update_data(
        own_time=value,
        own_time_is_approximate=is_approximate_time(
            time_text if time_text is not None else message.text
        ),
    )
    await state.set_state(BirthStates.own_place)
    admin_mode = bool(data.get("admin_generation"))
    if is_approximate_time(time_text if time_text is not None else message.text):
        prompt = (
            "Ничего страшного ❤️\n"
            "Разбор всё равно можно сделать. Некоторые выводы, связанные с домами "
            "и Асцендентом, будут менее точными.\n\n"
            "📍 ШАГ 4 ИЗ 4\n\n"
            "Напишите город и страну, где вы родились.\n"
            "Например: Москва, Россия"
        )
    else:
        prompt = (
            "📍 ШАГ 4 ИЗ 4\n\n"
            "Напишите город и страну, где вы родились.\n"
            "Например: Москва, Россия"
        )
    await message.answer(prompt, reply_markup=flow_back_keyboard(admin_mode=admin_mode))


@router.message(BirthStates.own_place)
async def own_place(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        latitude, longitude = geocode(message.text.strip())
    except ValueError as error:
        await message.answer(str(error))
        return
    if data.get("edit_field") == "place":
        profile = await get_profile(message.from_user.id)
        if not profile:
            await state.clear()
            await state.set_state(BirthStates.own_gender)
            await state.update_data(next_scenario="profile")
            await message.answer(
                "♀♂ ШАГ 1 ИЗ 4\n\n"
                "Выберите пол — это нужно для корректного обращения в разборе.\n"
                "♀ — женский, ♂ — мужской.",
                reply_markup=gender_keyboard(back_destination="menu"),
            )
            return
        profile.update(birth_place=message.text.strip(), latitude=latitude, longitude=longitude)
        await save_profile(message.from_user.id, profile)
        await state.clear()
        await message.answer("Данные сохранены ✅", reply_markup=back_to_edit_profile())
        return
    profile = {
        "birth_date": data["own_date"],
        "birth_time": data["own_time"],
        "time_is_approximate": data.get("own_time_is_approximate", False),
        "birth_place": message.text.strip(),
        "latitude": latitude,
        "longitude": longitude,
        "gender": normalize_gender(data.get("own_gender") or DEFAULT_GENDER),
    }
    await save_profile(message.from_user.id, profile)
    scenario_name = data.get("next_scenario")
    admin_mode = bool(data.get("admin_generation"))
    own_chart = calculate_chart(
        profile["birth_date"],
        profile["birth_time"],
        latitude,
        longitude,
        time_is_approximate=bool(profile["time_is_approximate"]),
    )
    if scenario_name == "profile":
        await state.clear()
        await message.answer("Профиль сохранён ✅", reply_markup=back_to_menu())
    elif scenario_name == "compatibility":
        await state.update_data(own_chart=own_chart, admin_generation=admin_mode)
        await state.set_state(BirthStates.partner_date)
        await message.answer(
            "📅 Дата рождения партнёра\n\n"
            "Напишите дату в формате ДД.ММ.ГГГГ.\n"
            "Например: 24.07.1998",
            reply_markup=flow_back_keyboard(admin_mode=admin_mode),
        )
    else:
        await state.clear()
        await show_teaser(
            message,
            scenario_name,
            own_chart,
            user_id=message.from_user.id,
            admin_mode=admin_mode,
        )


@router.message(BirthStates.partner_date)
async def partner_date(message: Message, state: FSMContext):
    try:
        value = parse_date(message.text)
    except (ValueError, TypeError):
        await message.answer("Используйте формат ДД.ММ.ГГГГ.")
        return
    await state.update_data(partner_date=value)
    await state.set_state(BirthStates.partner_time)
    data = await state.get_data()
    back_destination = "admin_gens" if data.get("admin_generation") else "menu"
    await message.answer(
        "🕐 Время рождения партнёра\n"
        "Например: 14:35\n\n"
        "Если время неизвестно, нажмите кнопку ниже.",
        reply_markup=unknown_time_keyboard(back_destination),
    )


@router.message(BirthStates.partner_time)
async def partner_time(message: Message, state: FSMContext, time_text: str | None = None):
    try:
        value = parse_time(time_text if time_text is not None else message.text)
    except (ValueError, TypeError):
        await message.answer("Введите ЧЧ:ММ или «не знаю».")
        return
    await state.update_data(
        partner_time=value,
        partner_time_is_approximate=is_approximate_time(
            time_text if time_text is not None else message.text
        ),
    )
    await state.set_state(BirthStates.partner_place)
    data = await state.get_data()
    await message.answer(
        "📍 Место рождения партнёра\n"
        "Например: Москва, Россия",
        reply_markup=flow_back_keyboard(admin_mode=bool(data.get("admin_generation"))),
    )


@router.callback_query(F.data == "time_unknown")
async def time_unknown(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()
    if current_state == BirthStates.own_time.state:
        await own_time(callback.message, state, "не знаю", callback.from_user.id)
    elif current_state == BirthStates.partner_time.state:
        await partner_time(callback.message, state, "не знаю")


@router.message(BirthStates.partner_place)
async def partner_place(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        latitude, longitude = geocode(message.text.strip())
    except ValueError as error:
        await message.answer(str(error))
        return
    partner = calculate_chart(
        data["partner_date"],
        data["partner_time"],
        latitude,
        longitude,
        time_is_approximate=data.get("partner_time_is_approximate", False),
    )
    await state.clear()
    await show_teaser(
        message,
        "compatibility",
        data["own_chart"],
        partner,
        user_id=message.from_user.id,
        admin_mode=bool(data.get("admin_generation")),
    )


async def show_teaser(
    message: Message,
    scenario_name: str,
    chart: dict,
    second_chart: dict | None = None,
    *,
    user_id: int,
    admin_mode: bool = False,
):
    PENDING_REPORTS[user_id] = (chart, second_chart)
    price = None if admin_mode else await get_report_price(scenario_name)
    offer_markup = pdf_offer_keyboard(scenario_name, admin_mode=admin_mode, price=price)
    fingerprint = birth_fingerprint(chart, second_chart)

    # Daily free limit applies to regular users only; admin gens stay unlimited for testing.
    if (
        not admin_mode
        and await get_free_daily_limit_enabled()
        and await has_used_free_today(user_id)
    ):
        await message.answer(
            "На сегодня бесплатный мини-разбор уже использован.\n\n"
            + PAID_OFFER_TEXTS.get(
                scenario_name,
                "Можно сразу открыть полный персональный PDF.",
            ),
            reply_markup=offer_markup,
        )
        return

    free_report_type = FREE_REPORT_TYPES.get(scenario_name)
    if free_report_type:
        await message.answer("Готовлю ваш бесплатный персональный мини-разбор…")
        free_content = None
        async with report_status_animation(message) as status:
            free_content = await generate_report_content(
                free_report_type,
                chart,
                second_chart,
                progress=status,
                gender=(await get_profile(user_id) or {}).get("gender"),
            )
            if free_content:
                status.mark_completed()
        if free_content:
            sections = free_content["sections"]
            if not sections:
                await message.answer(
                    "Не удалось сформировать бесплатный разбор прямо сейчас. "
                    "Можно сразу открыть полный PDF.\n\n"
                    + PAID_OFFER_TEXTS.get(scenario_name, ""),
                    reply_markup=offer_markup,
                )
                return
            report_id = store_pending_free_report(
                user_id,
                scenario_name,
                sections,
                admin_mode=admin_mode,
            )
            await save_free_generation(
                user_id,
                scenario_name,
                sections,
                fingerprint,
            )
            if not admin_mode:
                await mark_free_used_today(user_id)
            if admin_mode:
                await send_admin_usage_summary(message, free_content)
            await message.answer(
                f"<b>{free_content['title']}</b>\n{free_content['intro']}",
                parse_mode=ParseMode.HTML,
                reply_markup=free_section_keyboard(sections[0]["title"], report_id, 0),
            )
            return
        await message.answer(
            "Не удалось сформировать бесплатный разбор прямо сейчас. "
            "Можно сразу открыть полный PDF.\n\n"
            + PAID_OFFER_TEXTS.get(scenario_name, ""),
            reply_markup=offer_markup,
        )
        return

    await message.answer(
        "Не удалось подготовить бесплатный разбор для этого сценария. "
        "Можно сразу открыть полный PDF.\n\n"
        + PAID_OFFER_TEXTS.get(scenario_name, ""),
        reply_markup=offer_markup,
    )



@router.callback_query(F.data.startswith("free_section:"))
async def show_free_section(callback: CallbackQuery):
    parsed = parse_free_section_callback(callback.data or "")
    if parsed is None:
        await callback.answer("Раздел недоступен", show_alert=True)
        return
    report_id, section_index = parsed
    record = resolve_pending_free_report(callback.from_user.id, report_id)
    sections = record["sections"] if record else None
    if not record or not sections or not 0 <= section_index < len(sections):
        await callback.answer("Этот бесплатный разбор больше недоступен. Запустите новый.", show_alert=True)
        return

    await callback.answer()
    section = sections[section_index]
    text = f"<b>{section['title']}</b>\n\n{section['content']}"
    if len(text) > 4000:
        text = text[:3990] + "…"

    next_index = section_index + 1
    reply_markup = None
    if next_index < len(sections):
        reply_markup = free_section_keyboard(
            sections[next_index]["title"],
            record["id"],
            next_index,
        )

    with suppress(Exception):
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    if next_index == len(sections):
        scenario_name = record.get("scenario") or "personality"
        admin_mode = bool(record.get("admin_mode"))
        price = None if admin_mode else await get_report_price(scenario_name)
        await callback.message.answer(
            FREE_UPSELL_TEXTS.get(
                scenario_name,
                "Это бесплатный мини-разбор. Полный PDF раскрывает тему глубже.",
            ),
            reply_markup=pdf_offer_keyboard(
                scenario_name, admin_mode=admin_mode, price=price
            ),
        )


@router.callback_query(F.data == "menu")
async def back_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        await get_main_menu_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=await menu(callback.from_user.id),
    )


@router.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery):
    scenario_name = callback.data.split(":", 1)[1]
    if scenario_name not in PRICES:
        await callback.answer("Этот сценарий пока недоступен.", show_alert=True)
        return
    user_id = callback.from_user.id
    if not await _try_begin_report(user_id):
        await callback.answer("PDF уже формируется, подождите.", show_alert=True)
        return
    await _clear_callback_keyboard(callback)
    hold_lock = True
    try:
        amount = await get_report_price(scenario_name)
        order_id = await create_order(user_id, scenario_name, amount)
        charts = PENDING_REPORTS.get(user_id)
        if charts:
            await save_report_context(order_id, *charts)
        if await get_test_mode():
            await callback.answer("Тестовый заказ принят")
            await deliver_report(
                callback.message,
                user_id,
                callback.from_user,
                scenario_name,
                order_id,
                "TEST",
            )
            return
        # Invoice path: unlock until payment succeeds and deliver_report runs again.
        await _end_report(user_id)
        hold_lock = False
        payload = f"report:{scenario_name}:{order_id}"
        await callback.answer()
        await callback.message.answer(
            f"Ваш «{NAMES[scenario_name]}» будет сформирован индивидуально по вашим данным.\n\n"
            "Это не готовый текст для вашего знака — содержание зависит от даты, "
            "времени и места рождения.\n"
            "После оплаты вы получите полный персональный результат прямо здесь, в Telegram."
        )
        await callback.message.answer_invoice(
            title=NAMES[scenario_name], description="Персональный PDF-отчёт ASTRO MARY",
            payload=payload, currency="XTR",
            prices=[LabeledPrice(label=NAMES[scenario_name], amount=amount)],
            provider_token="",
        )
    finally:
        if hold_lock:
            await _end_report(user_id)


@router.callback_query(F.data.startswith("admin_buy:"))
async def admin_buy(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    scenario_name = callback.data.split(":", 1)[1]
    if scenario_name not in PRICES:
        await callback.answer("Этот сценарий пока недоступен.", show_alert=True)
        return
    user_id = callback.from_user.id
    if not await _try_begin_report(user_id):
        await callback.answer("PDF уже формируется, подождите.", show_alert=True)
        return
    await _clear_callback_keyboard(callback)
    try:
        order_id = await create_order(user_id, scenario_name, 0)
        charts = PENDING_REPORTS.get(user_id)
        if charts:
            await save_report_context(order_id, *charts)
        await callback.answer("Админ-заказ принят")
        await deliver_report(
            callback.message,
            user_id,
            callback.from_user,
            scenario_name,
            order_id,
            "ADMIN",
            admin_mode=True,
        )
    finally:
        await _end_report(user_id)


@router.pre_checkout_query()
async def pre_checkout(query):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def paid(message: Message):
    payment = message.successful_payment
    parts = payment.invoice_payload.split(":")
    if len(parts) != 3:
        await message.answer(
            "Платёж получен, но не удалось определить отчёт. Напишите в поддержку.",
            reply_markup=back_to_menu(),
        )
        return
    scenario_name, order_id = parts[1], int(parts[2])
    user_id = message.from_user.id
    if not await _try_begin_report(user_id):
        await message.answer("PDF уже формируется. Дождитесь окончания текущей сборки.")
        return
    try:
        await deliver_report(
            message,
            user_id,
            message.from_user,
            scenario_name,
            order_id,
            payment.telegram_payment_charge_id,
        )
    finally:
        await _end_report(user_id)


async def deliver_report(
    message: Message,
    user_id: int,
    recipient: User,
    scenario_name: str,
    order_id: int,
    payment_id: str,
    *,
    admin_mode: bool = False,
):
    await complete_order(order_id, payment_id)
    charts = await get_report_context(order_id) or PENDING_REPORTS.pop(user_id, None)
    # Only a back button — full generations menu under the PDF caused accidental
    # re-starts of scenarios from the document message.
    back_markup = back_to_admin_gens() if admin_mode else back_to_menu()
    if charts:
        chart, second_chart = charts
    elif scenario_name == "compatibility":
        # The partner chart cannot be restored from the profile: never fall back to one chart.
        await set_order_status(order_id, "report_pending")
        await message.answer(
            "Данные партнёра не сохранились, а разбор совместимости без них сделать нельзя. "
            "Оплата сохранена — выберите сценарий заново и введите данные партнёра.",
            reply_markup=back_markup,
        )
        return
    else:
        profile = await get_profile(user_id)
        if not profile:
            await message.answer(
                "Не удалось восстановить данные для отчёта. Выберите сценарий заново.",
                reply_markup=back_markup,
            )
            return
        chart = calculate_chart(
            profile["birth_date"],
            profile["birth_time"],
            profile["latitude"],
            profile["longitude"],
            time_is_approximate=bool(profile["time_is_approximate"]),
        )
        second_chart = None
    if admin_mode:
        await message.answer(
            "🧪 Админ-режим.\n"
            "Начинаю формировать полный PDF без оплаты. Это займёт несколько секунд."
        )
    else:
        await message.answer(
            "✅ Оплата получена.\n"
            "Начинаю формировать ваш персональный разбор. Это займёт несколько секунд."
        )
    async with report_status_animation(message) as status:
        prior_sections = await get_free_generation(
            user_id,
            scenario_name,
            birth_fingerprint(chart, second_chart),
        )
        profile = await get_profile(user_id)
        content = await generate_report_content(
            scenario_name,
            chart,
            second_chart,
            prior_sections=prior_sections,
            progress=status,
            gender=(profile or {}).get("gender"),
        )
        if content is None:
            await set_order_status(order_id, "report_pending")
            await message.answer(
                "Не удалось получить проверенный текст отчёта. Оплата сохранена — "
                "попробуйте сформировать PDF ещё раз."
                if not admin_mode
                else "Не удалось получить текст отчёта. Попробуйте сформировать PDF ещё раз.",
                reply_markup=retry_report_keyboard(order_id, admin_mode=admin_mode),
            )
            return
        status.mark_completed()
        profile_photo = await get_profile_photo(message, user_id)
        path = generate_report(
            scenario_name,
            chart,
            second_chart,
            content,
            recipient.full_name,
            recipient.username,
            profile_photo,
        )
    await message.answer_document(
        FSInputFile(path),
        caption=f"{NAMES[scenario_name]} · ASTRO MARY",
        reply_markup=back_markup,
    )
    if admin_mode:
        await send_admin_usage_summary(message, content)
    await set_order_status(order_id, "delivered")


def retry_report_keyboard(order_id: int, *, admin_mode: bool = False):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Сформировать PDF повторно", callback_data=f"retry_report:{order_id}")
    if admin_mode:
        builder.button(text="⬅️ К генерациям", callback_data="admin:generations")
    else:
        builder.button(text="⬅️ В меню", callback_data="back:menu")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data.startswith("retry_report:"))
async def retry_report(callback: CallbackQuery):
    try:
        order_id = int(callback.data.split(":", 1)[1])
    except (AttributeError, ValueError):
        await callback.answer("Не удалось определить заказ.", show_alert=True)
        return
    order = await get_order(order_id, callback.from_user.id)
    if not order or order["status"] not in {"paid", "report_pending"}:
        await callback.answer("Этот отчёт нельзя сформировать повторно.", show_alert=True)
        return
    user_id = callback.from_user.id
    admin_mode = (
        is_admin(user_id)
        and (
            str(order.get("telegram_payment_id") or "") == "ADMIN"
            or int(order.get("amount") or 0) == 0
        )
    )
    if not await _try_begin_report(user_id):
        await callback.answer("PDF уже формируется, подождите.", show_alert=True)
        return
    await _clear_callback_keyboard(callback)
    await callback.answer("Повторно формирую отчёт…")
    try:
        await deliver_report(
            callback.message,
            user_id,
            callback.from_user,
            order["report_type"],
            order_id,
            order["telegram_payment_id"] or "RETRY",
            admin_mode=admin_mode,
        )
    finally:
        await _end_report(user_id)


async def get_profile_photo(message: Message, user_id: int):
    try:
        photos = await message.bot.get_user_profile_photos(user_id, limit=1)
        if not photos.photos:
            return None
        file = await message.bot.get_file(photos.photos[0][-1].file_id)
        return await message.bot.download_file(file.file_path)
    except Exception:
        return None


class ReportStatusSession:
    def __init__(self, status_message: Message):
        self.status_message = status_message
        self.completed = False
        self.total = 0
        self.tasks: list[TaskProgress] = []
        self._next_step_id = 0
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._last_text: str | None = None
        self._animation: asyncio.Task | None = None

    async def configure(self, total: int) -> None:
        async with self._lock:
            self.total = max(0, int(total))
            self.tasks.clear()
            self._next_step_id = 0

    async def set_total(self, total: int) -> None:
        async with self._lock:
            self.total = max(0, int(total))

    async def start_step(self) -> int:
        async with self._lock:
            step_id = self._next_step_id
            self._next_step_id += 1
            self.tasks.append(
                TaskProgress(
                    started_at=asyncio.get_running_loop().time(),
                    step_id=step_id,
                )
            )
            return step_id

    async def finish_step(self, step_id: int) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            for task in self.tasks:
                if task.step_id == step_id and task.finishing_at is None:
                    task.finish_from = active_fraction(now - task.started_at)
                    task.finishing_at = now
                    break

    async def fail_step(self, step_id: int) -> None:
        async with self._lock:
            self.tasks = [task for task in self.tasks if task.step_id != step_id]

    def current_percent(self) -> float:
        return displayed_percent(
            self.total,
            self.tasks,
            asyncio.get_running_loop().time(),
        )

    async def _publish(self) -> None:
        text = f"{REPORT_PROGRESS_TEXT}… {format_progress_percent(self.current_percent())}"
        if text == self._last_text:
            return
        self._last_text = text
        with suppress(Exception):
            await self.status_message.edit_text(text)

    async def _animation_loop(self) -> None:
        while not self._stop.is_set():
            await self._publish()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=7.0)
            except asyncio.TimeoutError:
                continue

    def start_animation(self) -> None:
        self._animation = asyncio.create_task(self._animation_loop())

    async def stop_animation(self) -> None:
        self._stop.set()
        if self._animation is not None:
            with suppress(asyncio.CancelledError):
                await self._animation
            self._animation = None
        if self.completed:
            with suppress(Exception):
                await self.status_message.edit_text(f"{REPORT_PROGRESS_TEXT}… 100%")

    def mark_completed(self) -> None:
        self.completed = True


@asynccontextmanager
async def report_status_animation(message: Message):
    status_message = await message.answer(f"{REPORT_PROGRESS_TEXT}… 0%")
    session = ReportStatusSession(status_message)
    session.start_animation()
    try:
        yield session
    finally:
        await session.stop_animation()
        with suppress(Exception):
            await status_message.delete()


@router.message()
async def fallback_message(message: Message):
    await message.answer(
        await get_main_menu_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=await menu(message.from_user.id),
    )
