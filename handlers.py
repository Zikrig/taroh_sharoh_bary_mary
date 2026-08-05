from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ai_service import generate_report_content, get_aitunnel_balance
from astro import calculate_chart, geocode, parse_date, parse_time, teaser
from config import settings
from database import (
    complete_order,
    create_order,
    get_profile,
    get_app_setting,
    get_test_mode,
    save_profile,
    set_app_setting,
    set_test_mode,
)
from reports import generate_report

router = Router()
PRICES = {"personality": 349, "compatibility": 449, "money": 399}
NAMES = {"personality": "Разбор личности", "compatibility": "Совместимость", "money": "Денежный код"}
PENDING_REPORTS: dict[int, tuple[dict, dict | None]] = {}
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


async def menu():
    share_text = await get_app_setting("share_text") or "Узнай себя по звёздам →"
    builder = InlineKeyboardBuilder()
    builder.button(text="✨ Разбор личности", callback_data="scenario:personality")
    builder.button(text="💞 Совместимость", callback_data="scenario:compatibility")
    builder.button(text="💰 Денежный код", callback_data="scenario:money")
    builder.button(text="📤 Поделиться", switch_inline_query=share_text)
    builder.button(text="✏️ Изменить данные", callback_data="edit_profile")
    builder.button(text="📖 Инструкция", callback_data="help")
    builder.button(text="🆘 Поддержка", callback_data="support")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Главное меню", callback_data="menu")
    return builder.as_markup()


def admin_menu(test_mode: bool):
    builder = InlineKeyboardBuilder()
    label = "🟢 Тестовый режим: ВКЛ" if test_mode else "⚪ Тестовый режим: ВЫКЛ"
    builder.button(text=label, callback_data="admin:test_toggle")
    builder.button(text="✏️ Изменить текст поддержки", callback_data="admin:support_text")
    builder.button(text="📤 Изменить текст «Поделиться»", callback_data="admin:share_text")
    builder.adjust(1)
    return builder.as_markup()


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


@router.callback_query(F.data == "admin:support_text")
async def edit_support_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.support_text)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin:cancel_support_edit")
    await callback.message.answer(
        "Отправьте новый текст поддержки.\n"
        "Можно добавить ссылку, Telegram username и переносы строк.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "admin:share_text")
async def edit_share_text(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.share_text)
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="admin:cancel_share_edit")
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
        "Изменение текста «Поделиться» отменено.",
        reply_markup=admin_menu(await get_test_mode()),
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
    await message.answer("Текст «Поделиться» обновлён ✅", reply_markup=back_to_menu())


@router.callback_query(F.data == "admin:cancel_support_edit")
async def cancel_support_text_edit(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.answer("Изменение отменено")
    await callback.message.edit_text(
        "Изменение текста поддержки отменено.",
        reply_markup=admin_menu(await get_test_mode()),
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
    await message.answer("Текст поддержки обновлён ✅", reply_markup=back_to_menu())


@router.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Добро пожаловать в ASTRO MARY ✨\n\n"
        "Выберите сценарий — я построю карту по вашим данным, покажу короткий "
        "персональный тизер и предложу полный PDF.",
        reply_markup=await menu(),
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
async def profile(message: Message):
    data = await get_profile(message.from_user.id)
    if not data:
        await message.answer(
            "Профиль пока пуст. Выберите любой сценарий, чтобы заполнить его.",
            reply_markup=back_to_menu(),
        )
        return
    await message.answer(
        f"Ваш профиль:\n📅 {data['birth_date'][8:10]}.{data['birth_date'][5:7]}.{data['birth_date'][:4]}\n"
        f"🕐 {data['birth_time']}\n📍 {data['birth_place']}\n\n/edit — изменить",
        reply_markup=back_to_menu(),
    )


@router.message(Command("edit"))
async def edit(message: Message, state: FSMContext):
    await start_edit(message, state)


async def start_edit(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BirthStates.own_date)
    await state.update_data(next_scenario="profile")
    await message.answer("Введите вашу дату рождения в формате ДД.ММ.ГГГГ:")


@router.callback_query(F.data == "edit_profile")
async def edit_profile_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_edit(callback.message, state)


async def ask_own_data(message: Message, state: FSMContext, scenario: str):
    await message.answer(SCENARIO_INTROS[scenario])
    profile = await get_profile(message.from_user.id)
    if profile and scenario == "compatibility":
        own_chart = calculate_chart(profile["birth_date"], profile["birth_time"],
                                    profile["latitude"], profile["longitude"])
        await state.clear()
        await state.update_data(own_chart=own_chart, next_scenario=scenario)
        await state.set_state(BirthStates.partner_date)
        await message.answer("Профиль найден ✅\nВведите дату рождения партнёра ДД.ММ.ГГГГ:")
        return
    if profile:
        chart = calculate_chart(profile["birth_date"], profile["birth_time"], profile["latitude"], profile["longitude"])
        await show_teaser(message, scenario, chart)
        return
    await state.clear()
    await state.set_state(BirthStates.own_date)
    await state.update_data(next_scenario=scenario)
    await message.answer("Сколько вам лет?\nУкажите дату рождения в формате ДД.ММ.ГГГГ:")


@router.callback_query(F.data.startswith("scenario:"))
async def scenario(callback: CallbackQuery, state: FSMContext):
    scenario_name = callback.data.split(":", 1)[1]
    await callback.answer()
    await ask_own_data(callback.message, state, scenario_name)


@router.message(BirthStates.own_date)
async def own_date(message: Message, state: FSMContext):
    try:
        value = parse_date(message.text)
    except (ValueError, TypeError):
        await message.answer("Не понял дату. Используйте формат ДД.ММ.ГГГГ, например 21.03.1990.")
        return
    await state.update_data(own_date=value)
    await state.set_state(BirthStates.own_time)
    await message.answer("Введите время рождения ЧЧ:ММ или напишите «не знаю»:")


@router.message(BirthStates.own_time)
async def own_time(message: Message, state: FSMContext):
    try:
        value = parse_time(message.text)
    except (ValueError, TypeError):
        await message.answer("Нужно время в формате ЧЧ:ММ, например 14:30, или «не знаю».")
        return
    await state.update_data(own_time=value)
    await state.set_state(BirthStates.own_place)
    await message.answer("Напишите город и страну рождения:")


@router.message(BirthStates.own_place)
async def own_place(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        latitude, longitude = geocode(message.text.strip())
    except ValueError as error:
        await message.answer(str(error))
        return
    profile = {"birth_date": data["own_date"], "birth_time": data["own_time"],
               "birth_place": message.text.strip(), "latitude": latitude, "longitude": longitude}
    await save_profile(message.from_user.id, profile)
    scenario_name = data.get("next_scenario")
    own_chart = calculate_chart(profile["birth_date"], profile["birth_time"], latitude, longitude)
    if scenario_name == "profile":
        await state.clear()
        await message.answer("Профиль сохранён ✅", reply_markup=back_to_menu())
    elif scenario_name == "compatibility":
        await state.update_data(own_chart=own_chart)
        await state.set_state(BirthStates.partner_date)
        await message.answer("Теперь введите дату рождения партнёра ДД.ММ.ГГГГ:")
    else:
        await state.clear()
        await show_teaser(message, scenario_name, own_chart)


@router.message(BirthStates.partner_date)
async def partner_date(message: Message, state: FSMContext):
    try:
        value = parse_date(message.text)
    except (ValueError, TypeError):
        await message.answer("Используйте формат ДД.ММ.ГГГГ.")
        return
    await state.update_data(partner_date=value)
    await state.set_state(BirthStates.partner_time)
    await message.answer("Время рождения партнёра ЧЧ:ММ или «не знаю»:")


@router.message(BirthStates.partner_time)
async def partner_time(message: Message, state: FSMContext):
    try:
        value = parse_time(message.text)
    except (ValueError, TypeError):
        await message.answer("Введите ЧЧ:ММ или «не знаю».")
        return
    await state.update_data(partner_time=value)
    await state.set_state(BirthStates.partner_place)
    await message.answer("Город и страна рождения партнёра:")


@router.message(BirthStates.partner_place)
async def partner_place(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        latitude, longitude = geocode(message.text.strip())
    except ValueError as error:
        await message.answer(str(error))
        return
    partner = calculate_chart(data["partner_date"], data["partner_time"], latitude, longitude)
    await state.clear()
    await show_teaser(message, "compatibility", data["own_chart"], partner)


async def show_teaser(message: Message, scenario_name: str, chart: dict, second_chart: dict | None = None):
    PENDING_REPORTS[message.from_user.id] = (chart, second_chart)
    builder = InlineKeyboardBuilder()
    builder.button(text=f"🔓 Получить полный PDF · {PRICES[scenario_name]}⭐",
                   callback_data=f"buy:{scenario_name}")
    builder.button(text="🏠 В меню", callback_data="menu")
    builder.adjust(1)
    await message.answer(
        f"Ваш бесплатный тизер — {NAMES[scenario_name]}:\n\n{teaser(chart, scenario_name, second_chart)}\n\n"
        "Это только начало. Полный отчёт содержит подробный персональный разбор.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "menu")
async def back_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("Выберите сценарий:", reply_markup=await menu())


@router.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery):
    scenario_name = callback.data.split(":", 1)[1]
    order_id = await create_order(callback.from_user.id, scenario_name, PRICES[scenario_name])
    if await get_test_mode():
        await callback.answer("Тестовый заказ принят")
        await deliver_report(callback.message, scenario_name, order_id, "TEST")
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
    await deliver_report(message, scenario_name, order_id, payment.telegram_payment_charge_id)


async def deliver_report(message: Message, scenario_name: str, order_id: int, payment_id: str):
    await complete_order(order_id, payment_id)
    profile = await get_profile(message.from_user.id)
    if not profile:
        await message.answer(
            "Заказ принят. Сначала заполните профиль через /edit.",
            reply_markup=back_to_menu(),
        )
        return
    charts = PENDING_REPORTS.pop(message.from_user.id, None)
    chart = charts[0] if charts else calculate_chart(
        profile["birth_date"], profile["birth_time"], profile["latitude"], profile["longitude"]
    )
    second_chart = charts[1] if charts else None
    await message.answer("Заказ принят ✅ Готовлю ваш персональный отчёт…")
    content = await generate_report_content(scenario_name, chart, second_chart)
    path = generate_report(scenario_name, chart, second_chart, content)
    await message.answer_document(
        FSInputFile(path),
        caption=f"{NAMES[scenario_name]} · ASTRO MARY",
        reply_markup=back_to_menu(),
    )


@router.message()
async def fallback_message(message: Message):
    await message.answer(
        "Я помогу выбрать персональный астрологический разбор ✨\n"
        "Пожалуйста, выберите сценарий в главном меню.",
        reply_markup=await menu(),
    )
