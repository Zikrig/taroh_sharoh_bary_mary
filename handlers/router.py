import asyncio
from contextlib import asynccontextmanager, suppress
from random import uniform

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message, User
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.ai import AI_TIMEOUT_SECONDS, generate_report_content, get_aitunnel_balance
from services.astro import (
    calculate_chart,
    geocode,
    is_approximate_time,
    parse_date,
    parse_time,
)
from config.settings import settings
from database.repository import (
    complete_order,
    create_order,
    get_order,
    get_profile,
    get_app_setting,
    get_report_context,
    get_test_mode,
    save_profile,
    save_report_context,
    set_order_status,
    set_app_setting,
    set_test_mode,
)
from services.reports import generate_report

router = Router()
PRICES = {"personality": 349, "compatibility": 449, "money": 399}
NAMES = {"personality": "Разбор личности", "compatibility": "Совместимость", "money": "Денежный код"}
PENDING_REPORTS: dict[int, tuple[dict, dict | None]] = {}
REPORT_PROGRESS_TEXT = "Готовлю ваш персональный прогноз"
SCENARIO_INTROS = {
    "personality": (
        "✨ Разбор личности\n\n"
        "Ваша натальная карта — это персональный код характера, талантов, отношений "
        "и предназначения. Узнайте, в чём ваша сила и какие возможности раскрыть дальше."
    ),
    "compatibility": (
        "💞 Совместимость\n\n"
        "Разберём притяжение, эмоциональную близость, общение и возможные точки "
        "напряжения в вашей паре. Для анализа понадобятся данные вас и партнёра."
    ),
    "money": (
        "💰 Денежный код\n\n"
        "Карта поможет посмотреть ваши привычные финансовые сценарии, сильные стороны "
        "и направления, где легче раскрывать потенциал дохода."
    ),
}


class BirthStates(StatesGroup):
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


async def menu(user_id: int):
    share_text = await get_app_setting("share_text") or "Узнай себя по звёздам →"
    has_profile = await get_profile(user_id) is not None
    builder = InlineKeyboardBuilder()
    builder.button(text="✨ Разбор личности", callback_data="scenario:personality")
    builder.button(text="💞 Совместимость", callback_data="scenario:compatibility")
    builder.button(text="💰 Денежный код", callback_data="scenario:money")
    builder.button(text="📤 Поделиться", switch_inline_query=share_text)
    if has_profile:
        builder.button(text="✏️ Изменить данные", callback_data="edit_profile")
    builder.button(text="📖 Инструкция", callback_data="help")
    builder.button(text="🆘 Поддержка", callback_data="support")
    builder.adjust(1)
    return builder.as_markup()


async def get_main_menu_text() -> str:
    return await get_app_setting("main_menu_text") or (
        "Добро пожаловать в <b>ASTRO MARY</b> ✨\n\n"
        "Выберите сценарий — я построю карту по вашим данным, покажу короткий "
        "персональный тизер и предложу полный PDF."
    )


def back_keyboard(destination: str, text: str = "⬅️ Назад"):
    builder = InlineKeyboardBuilder()
    builder.button(text=text, callback_data=f"back:{destination}")
    return builder.as_markup()


def back_to_menu():
    return back_keyboard("menu")


def back_to_edit_profile():
    return back_keyboard("edit_profile")


def edit_profile_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Дата рождения", callback_data="edit:date")
    builder.button(text="🕐 Время рождения", callback_data="edit:time")
    builder.button(text="📍 Место рождения", callback_data="edit:place")
    builder.button(text="⬅️ Назад", callback_data="back:menu")
    builder.adjust(1)
    return builder.as_markup()


def unknown_time_keyboard(back_destination: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="Не знаю", callback_data="time_unknown")
    builder.button(text="⬅️ Назад", callback_data=f"back:{back_destination}")
    builder.adjust(1)
    return builder.as_markup()


def admin_menu(test_mode: bool):
    builder = InlineKeyboardBuilder()
    label = "🟢 Тестовый режим: ВКЛ" if test_mode else "⚪ Тестовый режим: ВЫКЛ"
    builder.button(text=label, callback_data="admin:test_toggle")
    builder.button(text="📝 Настройки текстов", callback_data="admin:texts")
    builder.adjust(1)
    return builder.as_markup()


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


def admin_text(test_mode: bool, balance_data: dict[str, float] | None) -> str:
    mode = "ВКЛ" if test_mode else "ВЫКЛ"
    if balance_data is None:
        balance = "недоступен — проверьте ключ AITUNNEL и подключение"
    else:
        balance = f"{balance_data['balance']:.2f} ₽"
    return (
        "Панель администратора\n\n"
        f"Баланс AITUNNEL: {balance}\n"
        f"Тестовый режим: {mode}\n\n"
        "В тестовом режиме реальные Telegram Stars не списываются: "
        "после нажатия кнопки покупки PDF формируется сразу."
    )


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


@router.message(Command("admin"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Команда доступна только администраторам.")
        return
    test_mode = await get_test_mode()
    balance = await get_aitunnel_balance()
    await message.answer(admin_text(test_mode, balance), reply_markup=admin_menu(test_mode))


@router.callback_query(F.data == "admin:test_toggle")
async def toggle_test_mode(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    enabled = not await get_test_mode()
    await set_test_mode(enabled)
    balance = await get_aitunnel_balance()
    await callback.answer("Тестовый режим включён" if enabled else "Тестовый режим выключен")
    await callback.message.edit_text(
        admin_text(enabled, balance),
        reply_markup=admin_menu(enabled),
    )


@router.callback_query(F.data == "admin:texts")
async def open_text_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(text_settings_message(), reply_markup=text_settings_menu())


@router.callback_query(F.data == "admin:back")
async def back_to_admin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    test_mode = await get_test_mode()
    balance = await get_aitunnel_balance()
    await callback.message.edit_text(admin_text(test_mode, balance), reply_markup=admin_menu(test_mode))


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
    elif destination == "edit_profile":
        await start_edit(callback.message, state, callback.from_user.id)
    elif destination == "text_settings" and is_admin(callback.from_user.id):
        await callback.message.answer(text_settings_message(), reply_markup=text_settings_menu())


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
    await callback.message.edit_text(text_settings_message(), reply_markup=text_settings_menu())


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
    await callback.message.edit_text(
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
    await callback.message.edit_text(
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
        "Выберите то, что хочется узнать о себе прямо сейчас ✨\n\n"
        "✨ Разбор личности — раскройте свои сильные стороны, таланты и внутренние "
        "ресурсы через вашу натальную карту.\n\n"
        "💞 Совместимость — узнайте, что объединяет вас с партнёром, где живёт "
        "притяжение и как сделать отношения гармоничнее.\n\n"
        "💰 Денежный код — найдите свои финансовые опоры, привычки и точки роста, "
        "чтобы увереннее двигаться к изобилию.\n\n"
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
        f"Ваш профиль:\n📅 {data['birth_date'][8:10]}.{data['birth_date'][5:7]}.{data['birth_date'][:4]}\n"
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
        await state.set_state(BirthStates.own_date)
        await state.update_data(next_scenario="profile")
        await message.answer(
            "Укажите дату рождения в формате ДД.ММ.ГГГГ:",
            reply_markup=back_to_menu(),
        )
        return
    await message.answer(
        "Ваши текущие данные:\n\n"
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
    if field == "date":
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


async def save_profile_field(message: Message, field: str, value: str, state: FSMContext) -> None:
    profile = await get_profile(message.from_user.id)
    if not profile:
        await state.clear()
        await state.set_state(BirthStates.own_date)
        await state.update_data(next_scenario="profile")
        await message.answer(
            "Укажите дату рождения в формате ДД.ММ.ГГГГ:",
            reply_markup=back_to_menu(),
        )
        return
    profile[field] = value
    await save_profile(message.from_user.id, profile)
    await message.answer("Данные сохранены ✅", reply_markup=back_to_edit_profile())


async def ask_own_data(message: Message, state: FSMContext, scenario: str, user_id: int):
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
        await state.update_data(own_chart=own_chart, next_scenario=scenario)
        await state.set_state(BirthStates.partner_date)
        await message.answer(
            "Профиль найден ✅\nВведите дату рождения партнёра ДД.ММ.ГГГГ:",
            reply_markup=back_to_menu(),
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
        await show_teaser(message, scenario, chart, user_id=user_id)
        return
    await state.clear()
    await state.set_state(BirthStates.own_date)
    await state.update_data(next_scenario=scenario)
    await message.answer(
        "Сколько вам лет?\nУкажите дату рождения в формате ДД.ММ.ГГГГ:",
        reply_markup=back_to_menu(),
    )


@router.callback_query(F.data.startswith("scenario:"))
async def scenario(callback: CallbackQuery, state: FSMContext):
    scenario_name = callback.data.split(":", 1)[1]
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
    await message.answer(
        "Введите время рождения ЧЧ:ММ или выберите вариант ниже:",
        reply_markup=unknown_time_keyboard("menu"),
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
    await message.answer("Напишите город и страну рождения:", reply_markup=back_to_menu())


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
            await state.set_state(BirthStates.own_date)
            await state.update_data(next_scenario="profile")
            await message.answer(
                "Укажите дату рождения в формате ДД.ММ.ГГГГ:",
                reply_markup=back_to_menu(),
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
    }
    await save_profile(message.from_user.id, profile)
    scenario_name = data.get("next_scenario")
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
        await state.update_data(own_chart=own_chart)
        await state.set_state(BirthStates.partner_date)
        await message.answer("Теперь введите дату рождения партнёра ДД.ММ.ГГГГ:")
    else:
        await state.clear()
        await show_teaser(message, scenario_name, own_chart, user_id=message.from_user.id)


@router.message(BirthStates.partner_date)
async def partner_date(message: Message, state: FSMContext):
    try:
        value = parse_date(message.text)
    except (ValueError, TypeError):
        await message.answer("Используйте формат ДД.ММ.ГГГГ.")
        return
    await state.update_data(partner_date=value)
    await state.set_state(BirthStates.partner_time)
    await message.answer(
        "Время рождения партнёра ЧЧ:ММ или выберите вариант ниже:",
        reply_markup=unknown_time_keyboard("menu"),
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
    await message.answer("Город и страна рождения партнёра:", reply_markup=back_to_menu())


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
    )


async def show_teaser(
    message: Message,
    scenario_name: str,
    chart: dict,
    second_chart: dict | None = None,
    *,
    user_id: int,
):
    PENDING_REPORTS[user_id] = (chart, second_chart)
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🔓 Получить полный PDF · {PRICES[scenario_name]}⭐",
                   callback_data=f"buy:{scenario_name}")
    builder.button(text="⬅️ Назад", callback_data="back:menu")
    builder.adjust(1)
    await message.answer(
        f"{NAMES[scenario_name]} · готово 35,0%",
        reply_markup=builder.as_markup(),
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
    order_id = await create_order(callback.from_user.id, scenario_name, PRICES[scenario_name])
    charts = PENDING_REPORTS.get(callback.from_user.id)
    if charts:
        await save_report_context(order_id, *charts)
    if await get_test_mode():
        await callback.answer("Тестовый заказ принят")
        await deliver_report(
            callback.message,
            callback.from_user.id,
            callback.from_user,
            scenario_name,
            order_id,
            "TEST",
        )
        return
    payload = f"report:{scenario_name}:{order_id}"
    await callback.answer()
    await callback.message.answer_invoice(
        title=NAMES[scenario_name], description="Персональный PDF-отчёт ASTRO MARY",
        payload=payload, currency="XTR",
        prices=[LabeledPrice(label=NAMES[scenario_name], amount=PRICES[scenario_name])],
    )


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
    await deliver_report(
        message,
        message.from_user.id,
        message.from_user,
        scenario_name,
        order_id,
        payment.telegram_payment_charge_id,
    )


async def deliver_report(
    message: Message,
    user_id: int,
    recipient: User,
    scenario_name: str,
    order_id: int,
    payment_id: str,
):
    await complete_order(order_id, payment_id)
    charts = await get_report_context(order_id) or PENDING_REPORTS.pop(user_id, None)
    if charts:
        chart, second_chart = charts
    else:
        profile = await get_profile(user_id)
        if not profile:
            await message.answer(
                "Не удалось восстановить данные для отчёта. Выберите сценарий заново.",
                reply_markup=back_to_menu(),
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
    async with report_status_animation(message) as mark_completed:
        content = await generate_report_content(scenario_name, chart, second_chart)
        if content is None:
            await set_order_status(order_id, "report_pending")
            await message.answer(
                "Не удалось получить проверенный текст отчёта. Оплата сохранена — "
                "попробуйте сформировать PDF ещё раз.",
                reply_markup=retry_report_keyboard(order_id),
            )
            return
        mark_completed()
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
        reply_markup=back_to_menu(),
    )
    await set_order_status(order_id, "delivered")


def retry_report_keyboard(order_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Сформировать PDF повторно", callback_data=f"retry_report:{order_id}")
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
    await callback.answer("Повторно формирую отчёт…")
    await deliver_report(
        callback.message,
        callback.from_user.id,
        callback.from_user,
        order["report_type"],
        order_id,
        order["telegram_payment_id"] or "RETRY",
    )


async def get_profile_photo(message: Message, user_id: int):
    try:
        photos = await message.bot.get_user_profile_photos(user_id, limit=1)
        if not photos.photos:
            return None
        file = await message.bot.get_file(photos.photos[0][-1].file_id)
        return await message.bot.download_file(file.file_path)
    except Exception:
        return None


async def _report_progress(status_message: Message, finished: asyncio.Event) -> None:
    progress = 0.0
    deadline = asyncio.get_running_loop().time() + AI_TIMEOUT_SECONDS * 1.2

    while not finished.is_set():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            progress = 99.9
            break
        pause = min(uniform(0.4, 15.0), remaining)
        try:
            await asyncio.wait_for(finished.wait(), timeout=pause)
            break
        except asyncio.TimeoutError:
            if progress < 99.9:
                progress = min(99.9, round(progress + uniform(0.1, 2.5), 1))
                with suppress(Exception):
                    await status_message.edit_text(
                        f"{REPORT_PROGRESS_TEXT}… {progress:.1f}%"
                    )

    if not finished.is_set():
        return

    start_progress = progress
    completion_deadline = asyncio.get_running_loop().time() + 10.0
    while progress < 100:
        remaining = completion_deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            progress = 100
        else:
            pause = min(uniform(0.4, 1.0), remaining)
            try:
                await asyncio.sleep(pause)
            except asyncio.CancelledError:
                raise
            elapsed = 10.0 - max(
                0.0,
                completion_deadline - asyncio.get_running_loop().time(),
            )
            progress = min(100.0, max(
                progress,
                round(start_progress + (100.0 - start_progress) * elapsed / 10.0, 1),
            ))
        with suppress(Exception):
            await status_message.edit_text(f"{REPORT_PROGRESS_TEXT}… {progress:.1f}%")


@asynccontextmanager
async def report_status_animation(message: Message):
    status_message = await message.answer(f"{REPORT_PROGRESS_TEXT}… 0,0%")
    finished = asyncio.Event()
    completed = False
    animation = asyncio.create_task(_report_progress(status_message, finished))

    def mark_completed() -> None:
        nonlocal completed
        completed = True

    try:
        yield mark_completed
    finally:
        if completed:
            finished.set()
            with suppress(asyncio.CancelledError):
                await animation
        else:
            animation.cancel()
            with suppress(asyncio.CancelledError):
                await animation
        with suppress(Exception):
            await status_message.delete()


@router.message()
async def fallback_message(message: Message):
    await message.answer(
        await get_main_menu_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=await menu(message.from_user.id),
    )
