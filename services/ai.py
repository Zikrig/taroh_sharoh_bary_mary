import json
import logging
import re
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.astro import SIGNS, calculate_synastry
from config.settings import settings
from services.report_prompts import (
    PAID_SECTION_BATCH,
    PRODUCT_PROMPTS,
    SECTION_DELIMITER,
    SYSTEM_PROMPT,
    output_format_block,
    product_prompt_for_titles,
    section_title_batches,
)
from services.reports_new import SECTIONS

logger = logging.getLogger(__name__)
AI_TIMEOUT_SECONDS = 360.0
FAILED_BATCH_RETRIES = 2
PAYLOAD_SAMPLES_DIR = Path("data/payload_samples")
MAX_CACHED_REPORTS = 128
MAX_SECTION_SUMMARY_CHARS = 220

# Kept for maintenance scripts that still import these names.
SECTION_RULES: dict[str, Any] = {}
SECTION_CONTEXT_FOCUS: dict[str, Any] = {}
MAX_HINT_CARDS = 6

PLANET_CODES = {
    "Солнце": "sun",
    "Луна": "moon",
    "Меркурий": "mercury",
    "Венера": "venus",
    "Марс": "mars",
    "Юпитер": "jupiter",
    "Сатурн": "saturn",
    "Уран": "uranus",
    "Нептун": "neptune",
    "Плутон": "pluto",
}
SIGN_CODES = {
    "Овен": "aries",
    "Телец": "taurus",
    "Близнецы": "gemini",
    "Рак": "cancer",
    "Лев": "leo",
    "Дева": "virgo",
    "Весы": "libra",
    "Скорпион": "scorpio",
    "Стрелец": "sagittarius",
    "Козерог": "capricorn",
    "Водолей": "aquarius",
    "Рыбы": "pisces",
}
ASPECT_CODES = {
    "соединение": "conjunction",
    "секстиль": "sextile",
    "квадрат": "square",
    "тригон": "trine",
    "оппозиция": "opposition",
}

FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"гарантирован", "гарантии результата"),
    (r"\bсуждено\b", "утверждение о судьбе"),
    (r"обречен|обречён", "утверждение о безысходности"),
    (r"(ты|вы|тебе|вам)\s+(точно|обязательно|наверняка|всегда|никогда)", "категоричное утверждение"),
    (r"(всегда|никогда)\s+(будешь|будете|сможешь|сможете)", "категоричное утверждение"),
    (r"обязательно\s+(будет|встрет|произойд|получ|станет)", "обещание события"),
    (r"100\s*%|сто процентов", "обещание вероятности"),
    (r"\bдиагноз", "медицинская формулировка"),
)

_REPORT_CACHE: dict[str, dict[str, Any]] = {}
SECTION_SPLIT = re.compile(rf"(?m)^{re.escape(SECTION_DELIMITER)}=*\s*$")


def _message_text(message: Any) -> str:
    """Extract the assistant reply text from an OpenAI-style chat message."""
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _is_timeout_error(error: BaseException) -> bool:
    name = type(error).__name__
    if name in {"TimeoutError", "APITimeoutError", "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout"}:
        return True
    return "timeout" in str(error).lower()


def _safe_path_part(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", (value or "").strip(), flags=re.UNICODE)
    return cleaned.strip("._") or "unknown"


def _payload_sample_attempt_dir(
    *,
    report_type: str,
    section_id: str,
    request_id: str,
    attempt: int,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return (
        PAYLOAD_SAMPLES_DIR
        / _safe_path_part(report_type)
        / _safe_path_part(section_id)
        / f"{timestamp}_a{attempt}_{request_id[:12]}"
    )


def _write_sample_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_sample_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _extract_reasoning(message: Any, dumped: dict[str, Any] | None) -> str:
    for source in (dumped or {}, message):
        if source is None:
            continue
        getter = source.get if isinstance(source, dict) else lambda key, default=None: getattr(source, key, default)
        for key in ("reasoning", "reasoning_content"):
            value = getter(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _save_request_transcript(
    sample_dir: Path,
    *,
    messages: list[dict[str, str]],
    request_meta: dict[str, Any],
) -> None:
    """Save the exact outbound payload: system prompt, user prompt, sampling params."""
    if not settings.save_payload_samples:
        return
    try:
        sample_dir.mkdir(parents=True, exist_ok=True)
        _write_sample_json(
            sample_dir / "03_request_as_sent.json",
            {**request_meta, "messages": messages},
        )
        if messages:
            _write_sample_text(sample_dir / "00_system.txt", messages[0].get("content") or "")
        if len(messages) > 1:
            _write_sample_text(sample_dir / "01_user.txt", messages[1].get("content") or "")
        if len(messages) > 2:
            extra = "\n\n".join(str(item.get("content") or "") for item in messages[2:])
            _write_sample_text(sample_dir / "02_retry.txt", extra)
    except (OSError, TypeError, ValueError) as error:
        logger.warning("Не удалось сохранить AI request в payload_samples: %s", error)


def _save_response_transcript(
    sample_dir: Path,
    *,
    content: str,
    word_count: int,
    finish_reason: Any,
    message: Any,
) -> None:
    """Save the model reply next to the request; keep reasoning in a separate file."""
    if not settings.save_payload_samples:
        return
    try:
        sample_dir.mkdir(parents=True, exist_ok=True)
        dumped = (
            message.model_dump()
            if hasattr(message, "model_dump")
            else {
                "content": getattr(message, "content", None),
                "reasoning": getattr(message, "reasoning", None),
                "reasoning_content": getattr(message, "reasoning_content", None),
            }
        )
        reasoning = _extract_reasoning(message, dumped if isinstance(dumped, dict) else None)
        _write_sample_text(sample_dir / "10_answer.txt", content or "")
        if reasoning:
            _write_sample_text(sample_dir / "11_reasoning.txt", reasoning)
        _write_sample_json(
            sample_dir / "12_response_meta.json",
            {
                "word_count": word_count,
                "finish_reason": finish_reason,
                "has_reasoning": bool(reasoning),
            },
        )
        _write_sample_json(sample_dir / "13_response_raw.json", dumped)
    except (OSError, TypeError, ValueError) as error:
        logger.warning("Не удалось сохранить AI response в payload_samples: %s", error)


def _sign_at(longitude: float) -> str:
    return SIGNS[int((longitude % 360) // 30)]


def _degree_in_sign(longitude: float) -> float:
    return round(longitude % 30, 1)


def _chart_for_prompt(chart: dict) -> dict[str, Any]:
    return {
        "birth_date": chart["date"],
        "birth_time_local": chart["time"],
        "birth_time_utc": chart["utc_time"],
        "timezone": chart["timezone"],
        "time_is_approximate": chart["time_is_approximate"],
        "latitude": chart.get("latitude"),
        "longitude": chart.get("longitude"),
        "ascendant": chart["ascendant"],
        "houses": chart["houses"],
        "planets": chart["planets"],
        "aspects": chart["aspects"],
    }


def _render_chart(chart: dict[str, Any], heading: str) -> str:
    lines = [heading]
    lines.append(f"Дата рождения: {chart['birth_date']}")
    time_note = " (время приблизительное)" if chart.get("time_is_approximate") else ""
    lines.append(f"Местное время: {chart['birth_time_local']}{time_note}")
    lines.append(f"UTC: {chart['birth_time_utc']}")
    lines.append(f"Часовой пояс: {chart['timezone']}")
    if chart.get("latitude") is not None and chart.get("longitude") is not None:
        lines.append(f"Координаты: {chart['latitude']}, {chart['longitude']}")
    if chart.get("time_is_approximate"):
        lines.append(
            "Время рождения приблизительное: дома и асцендент менее надёжны, "
            "но всё равно переданы полностью — учитывай это в интерпретации."
        )
    ascendant = chart.get("ascendant") or {}
    if ascendant:
        longitude = ascendant.get("longitude")
        sign = ascendant.get("sign") or (_sign_at(longitude) if longitude is not None else "")
        degree = f", {_degree_in_sign(float(longitude))}°" if longitude is not None else ""
        lines.append(f"Асцендент: {sign}{degree}")
    lines.append("")
    lines.append("Планеты:")
    for name, position in (chart.get("planets") or {}).items():
        lines.append(
            f"- {name}: {position['sign']}, {position['degree']}°, дом {position['house']}"
        )
    lines.append("")
    lines.append("Дома (куспиды):")
    for index, cusp in enumerate(chart.get("houses") or [], start=1):
        lines.append(f"- {index} дом: {_sign_at(float(cusp))} {_degree_in_sign(float(cusp))}°")
    lines.append("")
    lines.append("Аспекты:")
    aspects = chart.get("aspects") or []
    if not aspects:
        lines.append("- нет")
    for aspect in aspects:
        orb = aspect.get("orb")
        orb_text = f", орб {orb}" if orb is not None else ""
        lines.append(f"- {aspect['first']} {aspect['type']} {aspect['second']}{orb_text}")
    return "\n".join(lines)


def _facts_from_prompt_charts(
    primary_chart: dict[str, Any] | None,
    partner_chart: dict[str, Any] | None,
    synastry_aspects: list[dict[str, Any]] | None,
    *,
    include_ascendant: bool = True,
    use_labels: bool = True,
) -> list[str]:
    """Render citation strings from structured chart JSON."""
    facts: list[str] = []
    charts = [("Карта 1", primary_chart)]
    if use_labels:
        charts.append(("Карта 2", partner_chart))
    else:
        charts = [("", primary_chart)]
    for label_prefix, chart in charts:
        if chart is None:
            continue
        label = f"{label_prefix}: " if label_prefix else ""
        for planet, position in (chart.get("planets") or {}).items():
            facts.append(f"{label}{planet} в {position['sign']}, дом {position['house']}")
        if include_ascendant and chart.get("ascendant"):
            facts.append(f"{label}Асцендент в {chart['ascendant']['sign']}")
        for aspect in chart.get("aspects") or []:
            facts.append(f"{label}{aspect['first']} {aspect['type']} {aspect['second']}")
    for aspect in synastry_aspects or []:
        facts.append(f"Синастрия: {aspect['first']} {aspect['type']} {aspect['second']}")
    return facts


def _allowed_facts(chart: dict, second_chart: dict | None, report_type: str) -> list[str]:
    return _facts_from_prompt_charts(
        _chart_for_prompt(chart),
        _chart_for_prompt(second_chart) if second_chart else None,
        calculate_synastry(chart, second_chart) if second_chart else [],
        include_ascendant=True,
        use_labels=report_type in ("compatibility", "compatibility_free"),
    )


def _render_synastry(aspects: list[dict[str, Any]]) -> str:
    if not aspects:
        return "Синастрия:\n- нет значимых аспектов"
    lines = ["Синастрия:"]
    for aspect in aspects:
        orb = aspect.get("orb")
        orb_text = f", орб {orb}" if orb is not None else ""
        lines.append(
            f"- PERSON A {aspect['first']} {aspect['type']} PERSON B {aspect['second']}{orb_text}"
        )
    return "\n".join(lines)


def render_natal_dump(chart: dict, second_chart: dict | None, report_type: str) -> str:
    """Plain-text natal data sent to the model: planets, houses, aspects."""
    primary = _chart_for_prompt(chart)
    if report_type in ("compatibility", "compatibility_free"):
        if second_chart is None:
            raise ValueError("Для отчёта о совместимости нужны обе карты.")
        partner = _chart_for_prompt(second_chart)
        synastry = calculate_synastry(chart, second_chart)
        return "\n\n".join(
            [
                _render_chart(primary, "PERSON A — натальная карта"),
                _render_chart(partner, "PERSON B — натальная карта"),
                _render_synastry(synastry),
            ]
        )
    return _render_chart(primary, "Натальная карта")


def catalog_titles(report_type: str) -> list[str]:
    return [title for title, _ in SECTIONS[report_type]]


def build_prompt_payload(report_type: str, chart: dict, second_chart: dict | None) -> dict[str, Any]:
    if report_type not in SECTIONS:
        raise ValueError(f"Неизвестный тип отчёта: {report_type}")
    if report_type in ("compatibility", "compatibility_free") and second_chart is None:
        raise ValueError("Для отчёта о совместимости нужны обе карты.")
    if report_type not in PRODUCT_PROMPTS:
        raise ValueError(f"Не задан промпт для типа отчёта: {report_type}")
    titles = catalog_titles(report_type)
    natal_text = render_natal_dump(chart, second_chart, report_type)
    return {
        "report_type": report_type,
        "language": "ru",
        "sections": [{"title": title, "brief": brief} for title, brief in SECTIONS[report_type]],
        "primary_chart": _chart_for_prompt(chart),
        "partner_chart": _chart_for_prompt(second_chart) if second_chart else None,
        "synastry_aspects": calculate_synastry(chart, second_chart) if second_chart else [],
        "allowed_facts": _allowed_facts(chart, second_chart, report_type),
        "natal_text": natal_text,
        "user_prompt": build_user_prompt(report_type, natal_text, titles),
    }


def _covered_sections_block(covered: list[dict[str, str]]) -> str:
    if not covered:
        return ""
    lines = ["Уже написанные разделы — не повторяй их мысли, примеры и формулировки:"]
    for item in covered:
        lines.append(f"- {item['title']}: {item['summary']}")
    return "\n".join(lines)


def build_user_prompt(
    report_type: str,
    natal_text: str,
    titles: list[str],
    covered: list[dict[str, str]] | None = None,
) -> str:
    batch = True
    parts = [
        natal_text,
        product_prompt_for_titles(report_type, titles),
    ]
    covered_block = _covered_sections_block(covered or [])
    if covered_block:
        parts.append(covered_block)
    parts.append(output_format_block(titles, batch=batch))
    return "\n\n".join(parts)


def _section_summary(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= MAX_SECTION_SUMMARY_CHARS:
        return collapsed
    trimmed = collapsed[:MAX_SECTION_SUMMARY_CHARS].rsplit(" ", 1)[0]
    return f"{trimmed}…"


def _normalize_title(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^раздел\s*\d+\s*[:.\-–)]*\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\d{1,2}[.)]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .:")
    return text.casefold()


def _match_catalog_title(chunk: str, title_map: dict[str, str]) -> str | None:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return None
    candidates = [*lines, " ".join(lines)]
    for candidate in candidates:
        matched = title_map.get(_normalize_title(candidate))
        if matched:
            return matched
    return None


def _split_title_and_body(chunk: str, title_map: dict[str, str]) -> tuple[str | None, str]:
    lines = chunk.splitlines()
    for index, line in enumerate(lines):
        matched = _match_catalog_title(line, title_map)
        if matched:
            return matched, "\n".join(lines[index + 1 :]).strip()
    return None, chunk.strip()


def parse_delimited_sections(text: str, expected_titles: list[str]) -> tuple[list[dict[str, str]] | None, str | None]:
    """Split a one-shot model reply into catalog sections by ===== markers."""
    if not isinstance(text, str) or not text.strip():
        return None, "модель вернула пустой ответ"
    title_map = {_normalize_title(title): title for title in expected_titles}
    chunks = [part.strip() for part in SECTION_SPLIT.split(text) if part.strip()]
    if not chunks:
        return None, "в ответе нет разделителей ====="
    parsed: dict[str, str] = {}
    index = 0
    while index < len(chunks):
        title, body = _split_title_and_body(chunks[index], title_map)
        if title is None:
            index += 1
            continue
        if not body and index + 1 < len(chunks):
            next_title, _next_body = _split_title_and_body(chunks[index + 1], title_map)
            if next_title is None:
                body = chunks[index + 1].strip()
                index += 2
            else:
                index += 1
        else:
            index += 1
        if body:
            parsed[title] = body
    if len(parsed) < 2 and SECTION_DELIMITER not in text and not re.search(r"(?m)^={5,}\s*$", text):
        return None, "в ответе нет разделителей ====="
    missing = [title for title in expected_titles if not (parsed.get(title) or "").strip()]
    if missing:
        return None, "нет разделов: " + ", ".join(missing)
    return [{"title": title, "content": parsed[title]} for title in expected_titles], None


def _is_degenerate_section_text(text: str) -> str | None:
    """Reject model collapse: multilingual garbage, Latin soup, exotic scripts."""
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    exotic = len(re.findall(
        r"["
        r"\u0590-\u05FF"
        r"\u0600-\u06FF\u0750-\u077F"
        r"\u0900-\u097F"
        r"\u0E00-\u0E7F"
        r"\u3040-\u30FF\u4E00-\u9FFF"
        r"\uAC00-\uD7AF"
        r"]",
        text,
    ))
    letters = cyrillic + latin
    if exotic >= 8:
        return "в тексте слишком много символов чужих алфавитов"
    if letters >= 80:
        cyr_share = cyrillic / letters
        if cyr_share < 0.75:
            return (
                f"текст не похож на русский отчёт "
                f"(кириллица {cyr_share:.0%}, нужно ≥75%)"
            )
    camel = re.findall(r"\b[A-Z][a-z]+[A-Z][A-Za-z]{2,}\b", text)
    if len(camel) >= 6:
        return "в тексте много бессмысленных латиницей CamelCase-токенов"
    return None


def _forbidden_phrases(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for pattern, label in FORBIDDEN_PATTERNS:
        if re.search(pattern, lowered) and label not in found:
            found.append(label)
    return found


def _validate_section(
    content: Any,
    section: dict[str, Any],
    allowed_facts: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Accept non-empty Russian section text; length is only a prompt hint."""
    if not isinstance(content, str) or not content.strip():
        return None, "модель вернула пустой ответ"
    normalized = re.sub(r"\*\*(.*?)\*\*", r"\1", content.strip(), flags=re.DOTALL)
    normalized = normalized.replace("**", "")
    if not normalized.strip():
        return None, "модель вернула пустой ответ"
    degeneration = _is_degenerate_section_text(normalized)
    if degeneration:
        return None, degeneration
    return {
        "title": section["title"],
        "content": normalized,
        "references": allowed_facts[:3],
    }, None


def _validate_parsed_report(
    parsed: list[dict[str, str]],
    allowed_facts: list[str],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    validated: list[dict[str, Any]] = []
    for item in parsed:
        result, rejection = _validate_section(item["content"], item, allowed_facts)
        if result is None:
            return None, f"раздел «{item['title']}»: {rejection}"
        validated.append(result)
    return validated, None


def _report_cache_key(report_type: str, user_prompt: str) -> str:
    return sha1(f"{report_type}\n{user_prompt}".encode("utf-8")).hexdigest()


def _remember_report(key: str, report: dict[str, Any]) -> None:
    if key in _REPORT_CACHE:
        return
    while len(_REPORT_CACHE) >= MAX_CACHED_REPORTS:
        _REPORT_CACHE.pop(next(iter(_REPORT_CACHE)))
    _REPORT_CACHE[key] = report


def _report_shell(report_type: str) -> tuple[str, str]:
    titles = {
        "personality_free": "Ваш бесплатный персональный разбор",
        "love_free": "Ваш бесплатный любовный мини-разбор",
        "compatibility_free": "Ваш бесплатный мини-разбор пары",
        "money_free": "Ваш бесплатный денежный мини-разбор",
        "personality": "Ваш персональный разбор",
        "love": "Ваш любовный портрет",
        "compatibility": "Потенциал вашей совместимости",
        "money": "Ваш денежный код",
    }
    intros = {
        "personality_free": "Ниже — короткий символический портрет по вашей натальной карте.",
        "love_free": "Ниже — короткий символический портрет вашего стиля любви и близости.",
        "compatibility_free": "Ниже — короткий символический взгляд на динамику вашей пары.",
        "money_free": "Ниже — короткий символический портрет вашего отношения к ресурсам и реализации.",
        "personality": "Ниже — ключевые символические темы вашей натальной карты.",
        "love": "Ниже — ключевые символические темы вашего стиля любви и близости.",
        "compatibility": "Ниже — ключевые символические темы взаимодействия вашей пары.",
        "money": "Ниже — ключевые символические темы вашего отношения к ресурсам и реализации.",
    }
    return titles[report_type], intros[report_type]


async def _request_delimited_sections(
    client: Any,
    *,
    report_type: str,
    titles: list[str],
    user_prompt: str,
    allowed_facts: list[str],
    wave_id: str,
) -> list[dict[str, Any]] | None:
    request_id = uuid4().hex
    rejection: str | None = None
    for attempt in range(FAILED_BATCH_RETRIES + 1):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        if rejection:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Предыдущий вариант отклонён: {rejection}. "
                        "Исправь именно это. Верни только запрошенные разделы "
                        f"с разделителями {SECTION_DELIMITER} и точными названиями."
                    ),
                }
            )
        sample_dir = _payload_sample_attempt_dir(
            report_type=report_type,
            section_id=wave_id,
            request_id=request_id,
            attempt=attempt + 1,
        )
        _save_request_transcript(
            sample_dir,
            messages=messages,
            request_meta={
                "model": settings.ai_model,
                "temperature": settings.ai_temperature,
                "presence_penalty": settings.ai_presence_penalty,
                "frequency_penalty": settings.ai_frequency_penalty,
            },
        )
        try:
            response = await client.chat.completions.create(
                model=settings.ai_model,
                messages=messages,
                temperature=settings.ai_temperature,
                presence_penalty=settings.ai_presence_penalty,
                frequency_penalty=settings.ai_frequency_penalty,
            )
        except Exception as error:
            if _is_timeout_error(error) or isinstance(error, (TimeoutError, ValueError)):
                logger.warning(
                    "Не удалось получить отчёт «%s» (%s), попытка %s: %s",
                    report_type,
                    wave_id,
                    attempt + 1,
                    error,
                )
                rejection = str(error)
                continue
            logger.exception(
                "Неожиданная ошибка при генерации отчёта «%s» (%s)",
                report_type,
                wave_id,
            )
            return None
        message = response.choices[0].message
        raw_content = _message_text(message)
        _save_response_transcript(
            sample_dir,
            content=raw_content or "",
            word_count=len((raw_content or "").split()),
            finish_reason=getattr(response.choices[0], "finish_reason", None),
            message=message,
        )
        parsed, parse_rejection = parse_delimited_sections(raw_content, titles)
        if parsed is None:
            rejection = parse_rejection
            logger.warning(
                "AI вернул неотпарсенный отчёт «%s» (%s), попытка %s: %s",
                report_type,
                wave_id,
                attempt + 1,
                rejection,
            )
            continue
        validated, rejection = _validate_parsed_report(parsed, allowed_facts)
        if validated is None:
            logger.warning(
                "AI вернул некорректный отчёт «%s» (%s), попытка %s: %s",
                report_type,
                wave_id,
                attempt + 1,
                rejection,
            )
            continue
        return validated
    return None


async def generate_report_content(
    report_type: str, chart: dict, second_chart: dict | None = None
) -> dict[str, Any] | None:
    """Generate the report in waves of five sections and split each reply by =====."""
    if not settings.ai_api_key:
        return None
    try:
        from openai import AsyncOpenAI

        payload = build_prompt_payload(report_type, chart, second_chart)
        cache_key = _report_cache_key(report_type, payload["natal_text"])
        cached = _REPORT_CACHE.get(cache_key)
        if cached:
            return cached
        client = AsyncOpenAI(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            timeout=AI_TIMEOUT_SECONDS,
            max_retries=0,
        )
        titles = catalog_titles(report_type)
        batches = section_title_batches(titles, PAID_SECTION_BATCH)
        allowed_facts = payload["allowed_facts"]
        natal_text = payload["natal_text"]
        collected: list[dict[str, Any]] = []
        covered: list[dict[str, str]] = []
        for index, batch_titles in enumerate(batches, start=1):
            wave_id = f"wave{index:02d}"
            user_prompt = build_user_prompt(
                report_type,
                natal_text,
                batch_titles,
                covered,
            )
            validated = await _request_delimited_sections(
                client,
                report_type=report_type,
                titles=batch_titles,
                user_prompt=user_prompt,
                allowed_facts=allowed_facts,
                wave_id=wave_id,
            )
            if validated is None:
                return None
            collected.extend(validated)
            covered.extend(
                {
                    "title": item["title"],
                    "summary": _section_summary(item["content"]),
                }
                for item in validated
            )
        title, intro = _report_shell(report_type)
        result = {
            "title": title,
            "intro": intro,
            "sections": collected,
            "disclaimer": (
                "Материал носит символический и развлекательный характер и "
                "предназначен для саморефлексии."
            ),
        }
        _remember_report(cache_key, result)
        return result
    except (ImportError, ValueError) as error:
        logger.warning("Не удалось подготовить AI-отчёт: %s", error)
        return None
    except Exception:
        logger.exception("Неожиданная ошибка при сборке AI-отчёта")
        return None


async def get_aitunnel_balance() -> dict[str, float] | None:
    """Fetch the current AITUNNEL account balance without exposing the API key."""
    if not settings.ai_api_key:
        return None
    try:
        import httpx

        balance_url = f"{settings.ai_base_url.rstrip('/')}/aitunnel/balance"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                balance_url,
                headers={"Authorization": f"Bearer {settings.ai_api_key}"},
            )
            response.raise_for_status()
        data = response.json()
        balance = data.get("balance")
        if not isinstance(balance, (int, float)):
            return None
        return {"balance": float(balance)}
    except Exception:
        logger.exception("Не удалось получить баланс AITUNNEL")
        return None
