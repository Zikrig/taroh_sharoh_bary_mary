from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, LabeledPrice, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ai_service import generate_report_content
from astro import calculate_chart, geocode, parse_date, parse_time, teaser
from config import settings
from database import complete_order, create_order, get_profile, save_profile
from reports import generate_report

router = Router()
PRICES = {"personality": 349, "compatibility": 449, "money": 399}
NAMES = {"personality": "Разбор личности", "compatibility": "Совместимость", "money": "Денежный код"}
PENDING_REPORTS: dict[int, tuple[dict, dict | None]] = {}


class BirthStates(StatesGroup):
    own_date = State()
    own_time = State()
    own_place = State()
    partner_date = State()
    partner_time = State()
    partner_place = State()


def menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="✨ Разбор личности · 349⭐", callback_data="scenario:personality")
    builder.button(text="💞 Совместимость · 449⭐", callback_data="scenario:compatibility")
    builder.button(text="💰 Денежный код · 399⭐", callback_data="scenario:money")
    builder.button(text="📤 Поделиться", switch_inline_query="Узнай себя по звёздам →")
    builder.adjust(1)
    return builder.as_markup()


@router.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "Добро пожаловать в ASTRO MARY ✨\n\n"
        "Выберите отчёт — я построю карту по вашим данным, покажу короткий тизер "
        "и предложу полный персональный PDF.",
        reply_markup=menu(),
    )


@router.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Как пользоваться:\n"
        "1. Выберите сценарий.\n2. Введите дату в формате ДД.ММ.ГГГГ.\n"
        "3. Введите время ЧЧ:ММ или «не знаю».\n4. Укажите город и страну.\n\n"
        "/profile — сохранённые данные\n/edit — изменить данные\n/support — помощь"
    )


@router.message(Command("support"))
async def support(message: Message):
    await message.answer(f"По вопросам: {settings.support_url}")


@router.message(Command("profile"))
async def profile(message: Message):
    data = await get_profile(message.from_user.id)
    if not data:
        await message.answer("Профиль пока пуст. Выберите любой сценарий, чтобы заполнить его.", reply_markup=menu())
        return
    await message.answer(
        f"Ваш профиль:\n📅 {data['birth_date'][8:10]}.{data['birth_date'][5:7]}.{data['birth_date'][:4]}\n"
        f"🕐 {data['birth_time']}\n📍 {data['birth_place']}\n\n/edit — изменить"
    )


@router.message(Command("edit"))
async def edit(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BirthStates.own_date)
    await state.update_data(next_scenario="profile")
    await message.answer("Введите вашу дату рождения в формате ДД.ММ.ГГГГ:")


async def ask_own_data(message: Message, state: FSMContext, scenario: str):
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
    await message.answer("Введите вашу дату рождения в формате ДД.ММ.ГГГГ:")


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
        await message.answer("Профиль сохранён ✅", reply_markup=menu())
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
    await callback.message.answer("Выберите сценарий:", reply_markup=menu())


@router.callback_query(F.data.startswith("buy:"))
async def buy(callback: CallbackQuery):
    scenario_name = callback.data.split(":", 1)[1]
    order_id = await create_order(callback.from_user.id, scenario_name, PRICES[scenario_name])
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
        await message.answer("Платёж получен, но не удалось определить отчёт. Напишите в поддержку.")
        return
    scenario_name, order_id = parts[1], int(parts[2])
    await complete_order(order_id, payment.telegram_payment_charge_id)
    profile = await get_profile(message.from_user.id)
    if not profile:
        await message.answer("Платёж получен. Сначала заполните профиль через /edit.")
        return
    charts = PENDING_REPORTS.pop(message.from_user.id, None)
    chart = charts[0] if charts else calculate_chart(
        profile["birth_date"], profile["birth_time"], profile["latitude"], profile["longitude"]
    )
    second_chart = charts[1] if charts else None
    await message.answer("Оплата прошла ✅ Готовлю ваш персональный отчёт…")
    content = await generate_report_content(scenario_name, chart, second_chart)
    path = generate_report(scenario_name, chart, second_chart, content)
    await message.answer_document(FSInputFile(path), caption=f"{NAMES[scenario_name]} · ASTRO MARY")
