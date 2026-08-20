"""Admin UI for nested prompt editing."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from database.repository import (
    delete_free_generations_for_users,
    delete_prompt_override,
    ensure_prompt_defaults,
    get_active_prompts,
    get_all_prompt_defaults,
    get_all_prompt_overrides,
    get_prompt_default,
    get_prompt_override,
    restore_prompt_default,
    set_prompt_override,
)
from handlers.router import (
    AdminStates,
    _edit_or_answer,
    clear_pending_free_reports_for_users,
    is_admin,
)
from services.ai import clear_report_cache
from services.prompt_catalog import (
    MAX_PROMPT_CHARS,
    MAX_SECTION_TITLE_CHARS,
    REPORT_TYPE_LABELS,
    REPORT_TYPE_ORDER,
    SECTIONS_PAGE_SIZE,
    count_enabled_sections,
    default_prompt_text,
    general_nodes,
    is_known_prompt_key,
    missing_placeholders,
    node_for_key,
    parent_callback,
    parse_prompt_key,
    pipeline_nodes,
    product_intro_node,
    product_section_nodes,
    section_enabled_key,
    section_title_key,
    section_titles_for_product,
)
from services.report_prompts import apply_prompt_overrides

router = Router()
PREVIEW_LIMIT = 1800


def _marked(label: str, key: str, custom_keys: set[str]) -> str:
    return f"• {label}" if key in custom_keys else label


async def _prompt_maps() -> tuple[dict[str, str], dict[str, str], set[str]]:
    await ensure_prompt_defaults()
    defaults = await get_all_prompt_defaults()
    overrides = await get_all_prompt_overrides()
    custom = {
        key
        for key, text in overrides.items()
        if text and text != defaults.get(key)
    }
    return defaults, overrides, custom


def prompts_root_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="📜 Общие правила", callback_data="admin:prcat:general")
    builder.button(text="📦 Продукты", callback_data="admin:prcat:products")
    builder.button(text="🧩 Сборка запроса", callback_data="admin:prcat:pipeline")
    builder.button(text="⬅️ Назад", callback_data="admin:back")
    builder.adjust(1)
    return builder.as_markup()


def prompts_root_message() -> str:
    return (
        "Промпты генерации\n\n"
        "Дерево настроек:\n"
        "• Общие правила — системный промпт и промпт редактора.\n"
        "• Продукты — вступление и инструкция каждого раздела.\n"
        "• Сборка запроса — задумка, скелет, разворачивание, редактура, формат.\n\n"
        "• в начале кнопки — текст изменён относительно сохранённого значения по умолчанию.\n"
        "Кнопка «По умолчанию» возвращает исходный текст."
    )


def products_menu():
    builder = InlineKeyboardBuilder()
    for report_type in REPORT_TYPE_ORDER:
        builder.button(
            text=REPORT_TYPE_LABELS[report_type],
            callback_data=f"admin:prprod:{report_type}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin:prompts")
    builder.adjust(1)
    return builder.as_markup()


def products_message() -> str:
    return (
        "Продукты\n\n"
        "Сначала выберите тип разбора. "
        "Вступление и разделы будут на одном экране."
    )


async def general_menu():
    _defaults, _overrides, custom = await _prompt_maps()
    builder = InlineKeyboardBuilder()
    for node in general_nodes():
        builder.button(
            text=_marked(node.label, node.key, custom),
            callback_data=f"admin:predit:{node.key}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin:prompts")
    builder.adjust(1)
    return builder.as_markup()


def general_message() -> str:
    return (
        "Общие правила\n\n"
        "Системный промпт действует на генерацию разделов. "
        "Промпт редактора — на лёгкую правку готового текста."
    )


async def pipeline_menu():
    _defaults, _overrides, custom = await _prompt_maps()
    builder = InlineKeyboardBuilder()
    for node in pipeline_nodes():
        builder.button(
            text=_marked(node.label, node.key, custom),
            callback_data=f"admin:predit:{node.key}",
        )
    builder.button(text="⬅️ Назад", callback_data="admin:prompts")
    builder.adjust(1)
    return builder.as_markup()


def pipeline_message() -> str:
    return (
        "Сборка запроса\n\n"
        "Это каркас, в который подставляются карта, разделы и черновик. "
        "Плейсхолдеры в фигурных скобках лучше не удалять."
    )


def _button_text(label: str, limit: int = 64) -> str:
    if len(label) <= limit:
        return label
    return label[: limit - 1] + "…"


def build_product_keyboard(
    report_type: str,
    *,
    custom: set[str],
    overrides: dict[str, str],
    page: int = 0,
):
    intro = product_intro_node(report_type)
    nodes = product_section_nodes(report_type)
    pages = max(1, (len(nodes) + SECTIONS_PAGE_SIZE - 1) // SECTIONS_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * SECTIONS_PAGE_SIZE
    chunk = nodes[start:start + SECTIONS_PAGE_SIZE]
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_button_text(_marked(intro.label, intro.key, custom)),
            callback_data=f"admin:predit:{intro.key}",
        )
    )
    for index, node in enumerate(chunk, start=start):
        title = overrides.get(section_title_key(report_type, index)) or node.label
        enabled = overrides.get(section_enabled_key(report_type, index)) != "0"
        builder.row(
            InlineKeyboardButton(
                text=_button_text(_marked(f"{index + 1}. {title}", node.key, custom)),
                callback_data=f"admin:predit:{node.key}",
            ),
            InlineKeyboardButton(
                text="🟢" if enabled else "🔴",
                callback_data=f"admin:prsw:{node.key}",
            ),
        )
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"admin:prpage:{report_type}:{page - 1}",
            )
        )
    if page + 1 < pages:
        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"admin:prpage:{report_type}:{page + 1}",
            )
        )
    if nav:
        builder.row(*nav)
    builder.row(
        InlineKeyboardButton(text="⬅️ К продуктам", callback_data="admin:prcat:products")
    )
    return builder.as_markup(), page, pages, len(nodes)


async def product_menu(report_type: str, page: int = 0):
    _defaults, overrides, custom = await _prompt_maps()
    return build_product_keyboard(
        report_type,
        custom=custom,
        overrides=overrides,
        page=page,
    )


def product_message(report_type: str, page: int = 0, pages: int = 1, total: int = 0) -> str:
    extra = ""
    if pages > 1:
        extra = f"\nСтраница {page + 1}/{pages} · разделов {total}."
    return (
        f"{REPORT_TYPE_LABELS[report_type]}\n\n"
        "Вступление и разделы на одном экране. "
        "🟢 раздел идёт в генерацию, 🔴 — выключен. "
        "Название раздела открывает его настройки."
        f"{extra}"
    )


def edit_keyboard(key: str, *, custom: bool, enabled: bool | None = None):
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Скачать текущий", callback_data=f"admin:prfile:{key}")
    parsed = parse_prompt_key(key) or {}
    if parsed.get("kind") == "section":
        builder.button(text="✏️ Переименовать", callback_data=f"admin:prren:{key}")
        if enabled:
            builder.button(text="🟢 Включён", callback_data=f"admin:prwe:{key}")
        else:
            builder.button(text="🔴 Выключен", callback_data=f"admin:prwe:{key}")
    builder.button(text="По умолчанию", callback_data=f"admin:prreset:{key}")
    builder.button(text="⬅️ Назад", callback_data=parent_callback(key))
    builder.adjust(1)
    return builder.as_markup()


def rename_keyboard(key: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ К разделу", callback_data=f"admin:predit:{key}")
    builder.adjust(1)
    return builder.as_markup()


async def resolved_prompt_text(key: str) -> tuple[str, bool]:
    await ensure_prompt_defaults()
    default = await get_prompt_default(key) or default_prompt_text(key)
    override = await get_prompt_override(key)
    if override and override != default:
        return override, True
    return default, False


def edit_message(
    key: str,
    text: str,
    *,
    custom: bool,
    title: str | None = None,
    enabled: bool | None = None,
) -> str:
    node = node_for_key(key)
    label = title or (node.label if node else key)
    hint = node.hint if node else ""
    source = "изменён" if custom else "по умолчанию"
    preview = text if len(text) <= PREVIEW_LIMIT else text[: PREVIEW_LIMIT - 1] + "…"
    parts = [
        f"{label}\n",
        f"Ключ: {key}",
        f"Источник: {source} · {len(text)} симв.",
    ]
    if enabled is not None:
        parts.append("В генерации: включён" if enabled else "В генерации: выключен")
    if hint:
        parts.append(hint)
    parts.extend(
        [
            "",
            "Сейчас:",
            preview,
            "",
            "Пришлите новый текст сообщением или файлом .txt.",
        ]
    )
    return "\n".join(parts)


async def _editor_extras(key: str) -> tuple[str | None, bool | None]:
    parsed = parse_prompt_key(key)
    if not parsed or parsed.get("kind") != "section":
        return None, None
    node = node_for_key(key)
    title = await get_prompt_override(
        section_title_key(parsed["report_type"], parsed["index"])
    )
    flag = await get_prompt_override(
        section_enabled_key(parsed["report_type"], parsed["index"])
    )
    return title or (node.label if node else None), flag != "0"


async def _show_product_screen(
    message: Message,
    report_type: str,
    page: int = 0,
) -> None:
    markup, page, pages, total = await product_menu(report_type, page)
    await _edit_or_answer(
        message,
        product_message(report_type, page, pages, total),
        reply_markup=markup,
    )


async def _refresh_overrides() -> None:
    apply_prompt_overrides(await get_active_prompts())
    clear_report_cache()
    clear_pending_free_reports_for_users(settings.admin_ids)
    await delete_free_generations_for_users(settings.admin_ids)


async def _guard_admin(callback: CallbackQuery) -> bool:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return False
    return True


@router.callback_query(F.data == "admin:prompts")
async def open_prompts(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    await state.clear()
    await ensure_prompt_defaults()
    await callback.answer()
    await _edit_or_answer(
        callback.message,
        prompts_root_message(),
        reply_markup=prompts_root_menu(),
    )


@router.callback_query(F.data == "admin:prcat:general")
async def open_general(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    await state.clear()
    await callback.answer()
    await _edit_or_answer(
        callback.message,
        general_message(),
        reply_markup=await general_menu(),
    )


@router.callback_query(F.data == "admin:prcat:products")
async def open_products(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    await state.clear()
    await callback.answer()
    await _edit_or_answer(
        callback.message,
        products_message(),
        reply_markup=products_menu(),
    )


@router.callback_query(F.data == "admin:prcat:pipeline")
async def open_pipeline(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    await state.clear()
    await callback.answer()
    await _edit_or_answer(
        callback.message,
        pipeline_message(),
        reply_markup=await pipeline_menu(),
    )


@router.callback_query(F.data.startswith("admin:prprod:"))
async def open_product(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    report_type = (callback.data or "").split(":", 2)[-1]
    if report_type not in REPORT_TYPE_LABELS:
        await callback.answer("Неизвестный продукт.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await _show_product_screen(callback.message, report_type, 0)


@router.callback_query(F.data.startswith("admin:prpage:"))
async def open_sections_page(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    parts = (callback.data or "").split(":")
    # admin:prpage:{report_type}:{page}
    if len(parts) != 4:
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    report_type, page_text = parts[2], parts[3]
    if report_type not in REPORT_TYPE_LABELS or not page_text.isdigit():
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    await state.clear()
    await callback.answer()
    await _show_product_screen(callback.message, report_type, int(page_text))


async def _show_prompt_editor(
    message: Message,
    state: FSMContext,
    key: str,
    *,
    attach_full: bool = True,
) -> None:
    text, custom = await resolved_prompt_text(key)
    title, enabled = await _editor_extras(key)
    await state.set_state(AdminStates.prompt_text)
    await state.update_data(prompt_key=key)
    await _edit_or_answer(
        message,
        edit_message(key, text, custom=custom, title=title, enabled=enabled),
        reply_markup=edit_keyboard(key, custom=custom, enabled=enabled),
    )
    if attach_full and len(text) > PREVIEW_LIMIT:
        await message.answer_document(
            BufferedInputFile(text.encode("utf-8"), filename=f"{key}.txt"),
            caption="Полный текущий текст",
        )


@router.callback_query(F.data.startswith("admin:predit:"))
async def edit_prompt(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    key = (callback.data or "").split(":", 2)[-1]
    if not is_known_prompt_key(key):
        await callback.answer("Неизвестный промпт.", show_alert=True)
        return
    await callback.answer()
    await _show_prompt_editor(callback.message, state, key)


@router.callback_query(F.data.startswith("admin:prfile:"))
async def download_prompt(callback: CallbackQuery):
    if not await _guard_admin(callback):
        return
    key = (callback.data or "").split(":", 2)[-1]
    if not is_known_prompt_key(key):
        await callback.answer("Неизвестный промпт.", show_alert=True)
        return
    text, _custom = await resolved_prompt_text(key)
    node = node_for_key(key)
    await callback.answer()
    await callback.message.answer_document(
        BufferedInputFile(text.encode("utf-8"), filename=f"{key}.txt"),
        caption=node.label if node else key,
    )


@router.callback_query(F.data.startswith("admin:prreset:"))
async def reset_prompt(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    key = (callback.data or "").split(":", 2)[-1]
    if not is_known_prompt_key(key):
        await callback.answer("Неизвестный промпт.", show_alert=True)
        return
    await restore_prompt_default(key)
    await _refresh_overrides()
    await callback.answer("Вернул значение по умолчанию")
    await _show_prompt_editor(callback.message, state, key)


def _section_parsed(key: str) -> dict[str, str] | None:
    parsed = parse_prompt_key(key)
    if parsed is None or parsed.get("kind") != "section":
        return None
    return parsed


async def _toggle_section_flag(key: str) -> tuple[bool | None, str | None]:
    parsed = _section_parsed(key)
    if parsed is None:
        return None, "Это не раздел."
    report_type = parsed["report_type"]
    index = parsed["index"]
    flag_key = section_enabled_key(report_type, index)
    currently_enabled = (await get_prompt_override(flag_key)) != "0"
    if currently_enabled:
        overrides = await get_all_prompt_overrides()
        overrides[flag_key] = "0"
        if count_enabled_sections(report_type, overrides) < 1:
            return None, "Нужен хотя бы один включённый раздел."
        await set_prompt_override(flag_key, "0")
        await _refresh_overrides()
        return False, None
    await delete_prompt_override(flag_key)
    await _refresh_overrides()
    return True, None


@router.callback_query(F.data.startswith("admin:prsw:"))
async def toggle_section_from_list(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    key = (callback.data or "").split(":", 2)[-1]
    enabled, error = await _toggle_section_flag(key)
    if error:
        await callback.answer(error, show_alert=True)
        return
    parsed = _section_parsed(key)
    await callback.answer("Раздел включён" if enabled else "Раздел выключен")
    if parsed is None:
        return
    page = int(parsed["index"]) // SECTIONS_PAGE_SIZE
    await state.clear()
    await _show_product_screen(callback.message, parsed["report_type"], page)


@router.callback_query(F.data.startswith("admin:prwe:"))
async def toggle_section_from_editor(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    key = (callback.data or "").split(":", 2)[-1]
    enabled, error = await _toggle_section_flag(key)
    if error:
        await callback.answer(error, show_alert=True)
        return
    await callback.answer("Раздел включён" if enabled else "Раздел выключен")
    await _show_prompt_editor(callback.message, state, key, attach_full=False)


@router.callback_query(F.data.startswith("admin:prren:"))
async def start_rename_section(callback: CallbackQuery, state: FSMContext):
    if not await _guard_admin(callback):
        return
    key = (callback.data or "").split(":", 2)[-1]
    parsed = _section_parsed(key)
    if parsed is None or not is_known_prompt_key(key):
        await callback.answer("Это не раздел.", show_alert=True)
        return
    title, _enabled = await _editor_extras(key)
    await state.set_state(AdminStates.prompt_title)
    await state.update_data(prompt_key=key)
    await callback.answer()
    await _edit_or_answer(
        callback.message,
        (
            f"{title or key}\n\n"
            f"Пришлите новое название раздела одним сообщением "
            f"(до {MAX_SECTION_TITLE_CHARS} символов)."
        ),
        reply_markup=rename_keyboard(key),
    )


@router.message(AdminStates.prompt_title)
async def save_section_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Команда доступна только администраторам.")
        return
    data = await state.get_data()
    key = str(data.get("prompt_key") or "")
    parsed = _section_parsed(key)
    if parsed is None or not is_known_prompt_key(key):
        await state.clear()
        await message.answer("Откройте раздел заново через админку.")
        return
    if message.document:
        await message.answer("Для названия нужен обычный текст, не файл.")
        return
    title = " ".join((message.text or "").split())
    if not title:
        await message.answer("Название не должно быть пустым.")
        return
    if len(title) > MAX_SECTION_TITLE_CHARS:
        await message.answer(
            f"Слишком длинно: максимум {MAX_SECTION_TITLE_CHARS} символов."
        )
        return
    report_type = parsed["report_type"]
    index = int(parsed["index"])
    overrides = await get_all_prompt_overrides()
    current_titles = section_titles_for_product(report_type, overrides)
    wanted = title.casefold()
    for other_index, other_title in enumerate(current_titles):
        if other_index != index and other_title.casefold() == wanted:
            await message.answer(
                f"Название «{other_title}» уже есть у другого раздела этого продукта."
            )
            return
    node = node_for_key(key)
    default_title = node.label if node else title
    title_key = section_title_key(report_type, index)
    if title == default_title:
        await delete_prompt_override(title_key)
    else:
        await set_prompt_override(title_key, title)
    await _refresh_overrides()
    await state.set_state(AdminStates.prompt_text)
    await state.update_data(prompt_key=key)
    text, custom = await resolved_prompt_text(key)
    _current_title, enabled = await _editor_extras(key)
    await message.answer(
        edit_message(key, text, custom=custom, title=title, enabled=enabled)
        + f"\n\nНазвание обновлено: {title}",
        reply_markup=edit_keyboard(key, custom=custom, enabled=enabled),
    )


async def _read_prompt_payload(message: Message) -> tuple[str | None, str | None]:
    if message.document:
        name = (message.document.file_name or "").lower()
        if not name.endswith((".txt", ".md")):
            return None, "Нужен файл .txt или .md."
        size = message.document.file_size or 0
        if size > MAX_PROMPT_CHARS * 4:
            return None, "Файл слишком большой."
        buffer = await message.bot.download(message.document)
        raw = buffer.read() if buffer is not None else b""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, "Файл должен быть в UTF-8."
        return text.strip(), None
    text = (message.text or "").strip()
    if not text:
        return None, "Текст не должен быть пустым."
    return text, None


@router.message(AdminStates.prompt_text)
async def save_prompt(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        await message.answer("Команда доступна только администраторам.")
        return
    data = await state.get_data()
    key = str(data.get("prompt_key") or "")
    if not is_known_prompt_key(key):
        await state.clear()
        await message.answer("Откройте промпт заново через админку.")
        return
    text, error = await _read_prompt_payload(message)
    if error:
        await message.answer(error)
        return
    if text is None:
        await message.answer("Текст не должен быть пустым.")
        return
    if len(text) > MAX_PROMPT_CHARS:
        await message.answer(f"Слишком длинно: максимум {MAX_PROMPT_CHARS} символов.")
        return
    missing = missing_placeholders(key, text)
    if missing:
        names = " ".join("{" + name + "}" for name in missing)
        await message.answer(
            f"В шаблоне не хватает плейсхолдеров: {names}. "
            "Верните их или откройте текущий текст через «Скачать»."
        )
        return
    default = await get_prompt_default(key) or default_prompt_text(key)
    if text == default:
        await delete_prompt_override(key)
        custom = False
        status = "возвращён к значению по умолчанию"
    else:
        await set_prompt_override(key, text)
        custom = True
        status = "обновлён"
    await _refresh_overrides()
    title, enabled = await _editor_extras(key)
    node = node_for_key(key)
    label = title or (node.label if node else key)
    await state.update_data(prompt_key=key)
    await message.answer(
        f"{label} {status} ✅\nМожно прислать ещё одну версию или нажать «По умолчанию».",
        reply_markup=edit_keyboard(key, custom=custom, enabled=enabled),
    )
