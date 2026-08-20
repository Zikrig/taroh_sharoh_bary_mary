"""Editable prompt tree for admin: keys, labels, defaults, validation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from services.report_prompts import (
    EDITOR_SYSTEM_PROMPT,
    PIPELINE_PLACEHOLDERS,
    PIPELINE_TEMPLATES,
    PRODUCT_PROMPTS,
    SYSTEM_PROMPT,
    default_product_parts,
)

PROMPT_SETTING_PREFIX = "prompt:"
MAX_PROMPT_CHARS = 50_000
MAX_SECTION_TITLE_CHARS = 60
SECTIONS_PAGE_SIZE = 8

REPORT_TYPE_ORDER = (
    "personality_free",
    "personality",
    "love_free",
    "love",
    "money_free",
    "money",
    "compatibility_free",
    "compatibility",
)

REPORT_TYPE_LABELS = {
    "personality_free": "🧠 Личность · бесплатно",
    "personality": "🧠 Личность · PDF",
    "love_free": "❤️ Любовь · бесплатно",
    "love": "❤️ Любовь · PDF",
    "money_free": "💰 Деньги · бесплатно",
    "money": "💰 Деньги · PDF",
    "compatibility_free": "💑 Совместимость · бесплатно",
    "compatibility": "💑 Совместимость · PDF",
}

PIPELINE_ITEMS = (
    ("concept", "Общая задумка PDF"),
    ("ask_concept", "Короткая задумка в скелете"),
    ("skeleton", "Скелет раздела"),
    ("expand", "Разворачивание раздела"),
    ("editorial", "Редактура"),
    ("format", "Формат ответа"),
)

PIPELINE_HINTS = {
    "concept": "Плейсхолдеры: {report_type} {listed} {prior}",
    "ask_concept": "Без плейсхолдеров. Текст, если задумка ещё не собрана.",
    "skeleton": "Без плейсхолдеров. Инструкция к черновику раздела.",
    "expand": "Плейсхолдер: {concept_clause} — « и общую задумку» или пусто.",
    "editorial": "Плейсхолдеры: {scope} {full_draft} {return_line} {listed}",
    "format": "Плейсхолдеры: {scope} {delimiter} {example} {listed} {limits}",
}


@dataclass(frozen=True)
class PromptNode:
    key: str
    label: str
    hint: str = ""


def section_enabled_key(report_type: str, index: int | str) -> str:
    return f"on.{report_type}.{index}"


def section_title_key(report_type: str, index: int | str) -> str:
    return f"t.{report_type}.{index}"


def _default_section_titles(report_type: str) -> list[str]:
    from services.reports_new import SECTIONS

    return [title for title, _ in SECTIONS.get(report_type, ())]


def _section_nodes(report_type: str) -> list[PromptNode]:
    _intro, blocks = default_product_parts(report_type)
    catalog = _default_section_titles(report_type)
    nodes: list[PromptNode] = []
    for index, (header, _body) in enumerate(blocks):
        fallback = " ".join(line.strip() for line in header.splitlines() if line.strip())
        title = catalog[index] if index < len(catalog) else fallback
        nodes.append(
            PromptNode(
                key=f"s.{report_type}.{index}",
                label=title or f"Раздел {index + 1}",
                hint="Инструкция к этому разделу. Название меняется кнопкой «Переименовать».",
            )
        )
    return nodes


def product_intro_node(report_type: str) -> PromptNode:
    return PromptNode(
        key=f"i.{report_type}",
        label="Вступление продукта",
        hint="Общая задача и тон до списка разделов.",
    )


def product_section_nodes(report_type: str) -> list[PromptNode]:
    if report_type not in PRODUCT_PROMPTS:
        return []
    return _section_nodes(report_type)


def general_nodes() -> list[PromptNode]:
    return [
        PromptNode(
            "sys",
            "Системный промпт",
            "Правила письма для генерации разделов. Длинный текст удобнее прислать файлом .txt.",
        ),
        PromptNode(
            "ed",
            "Промпт редактора",
            "Системные правила лёгкой редактуры готового текста.",
        ),
    ]


def pipeline_nodes() -> list[PromptNode]:
    return [
        PromptNode(f"p.{name}", label, PIPELINE_HINTS[name])
        for name, label in PIPELINE_ITEMS
    ]


@lru_cache(maxsize=1)
def all_prompt_keys() -> frozenset[str]:
    keys = {node.key for node in general_nodes()}
    keys.update(node.key for node in pipeline_nodes())
    for report_type in REPORT_TYPE_ORDER:
        keys.add(product_intro_node(report_type).key)
        keys.update(node.key for node in product_section_nodes(report_type))
    return frozenset(keys)


def is_known_prompt_key(key: str) -> bool:
    return key in all_prompt_keys()


def parse_prompt_key(key: str) -> dict[str, str] | None:
    if key in {"sys", "ed"}:
        return {"kind": key}
    if key.startswith("i."):
        report_type = key[2:]
        if report_type in PRODUCT_PROMPTS:
            return {"kind": "intro", "report_type": report_type}
        return None
    if key.startswith("s."):
        rest = key[2:]
        report_type, sep, index_text = rest.rpartition(".")
        if not sep or report_type not in PRODUCT_PROMPTS or not index_text.isdigit():
            return None
        return {"kind": "section", "report_type": report_type, "index": index_text}
    if key.startswith("p."):
        name = key[2:]
        if name in PIPELINE_TEMPLATES:
            return {"kind": "pipeline", "name": name}
        return None
    return None


def node_for_key(key: str) -> PromptNode | None:
    parsed = parse_prompt_key(key)
    if parsed is None:
        return None
    kind = parsed["kind"]
    if kind == "sys":
        return general_nodes()[0]
    if kind == "ed":
        return general_nodes()[1]
    if kind == "intro":
        return product_intro_node(parsed["report_type"])
    if kind == "section":
        nodes = product_section_nodes(parsed["report_type"])
        index = int(parsed["index"])
        if 0 <= index < len(nodes):
            return nodes[index]
        return None
    if kind == "pipeline":
        for node in pipeline_nodes():
            if node.key == key:
                return node
    return None


def default_prompt_text(key: str) -> str:
    parsed = parse_prompt_key(key)
    if parsed is None:
        raise KeyError(key)
    kind = parsed["kind"]
    if kind == "sys":
        return SYSTEM_PROMPT
    if kind == "ed":
        return EDITOR_SYSTEM_PROMPT
    if kind == "intro":
        intro, _blocks = default_product_parts(parsed["report_type"])
        return intro
    if kind == "section":
        _intro, blocks = default_product_parts(parsed["report_type"])
        index = int(parsed["index"])
        return blocks[index][1]
    if kind == "pipeline":
        return PIPELINE_TEMPLATES[parsed["name"]]
    raise KeyError(key)


def count_enabled_sections(report_type: str, overrides: dict[str, str]) -> int:
    total = len(product_section_nodes(report_type))
    return sum(
        1
        for index in range(total)
        if overrides.get(section_enabled_key(report_type, index)) != "0"
    )


def section_titles_for_product(report_type: str, overrides: dict[str, str]) -> list[str]:
    return [
        (overrides.get(section_title_key(report_type, index)) or node.label).strip()
        for index, node in enumerate(product_section_nodes(report_type))
    ]


def missing_placeholders(key: str, text: str) -> list[str]:
    parsed = parse_prompt_key(key)
    if parsed is None or parsed["kind"] != "pipeline":
        return []
    required = PIPELINE_PLACEHOLDERS[parsed["name"]]
    return [name for name in required if "{" + name + "}" not in text]


def parent_callback(key: str) -> str:
    parsed = parse_prompt_key(key) or {}
    kind = parsed.get("kind")
    if kind in {"sys", "ed"}:
        return "admin:prcat:general"
    if kind in {"intro", "section"}:
        report_type = parsed["report_type"]
        if kind == "section":
            index = int(parsed["index"])
            page = index // SECTIONS_PAGE_SIZE
            return f"admin:prpage:{report_type}:{page}"
        return f"admin:prprod:{report_type}"
    if kind == "pipeline":
        return "admin:prcat:pipeline"
    return "admin:prompts"
