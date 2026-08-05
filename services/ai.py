import json
import logging
from typing import Any

from services.astro import calculate_synastry
from config.settings import settings
from services.reports import SECTIONS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Ты — автор персональных астрологических отчётов. Подготовь отчёт строго на русском языке.
Используй только факты из переданных расчётов: не придумывай положения планет, дома, аспекты
или события. Обращайся к читателю на «вы», пиши живо, бережно и без повторов.

Нельзя давать диагнозы, медицинские назначения, юридические или инвестиционные советы,
гарантировать доход, отношения или будущие события. Астрологические интерпретации подавай
как символический, развлекательный способ саморефлексии, а не как установленный факт.

Верни только JSON без Markdown:
{
  "title": "string",
  "intro": "string",
  "sections": [{"title": "string", "content": "string"}],
  "disclaimer": "string"
}
Список sections должен содержать каждый переданный раздел ровно один раз и в том же порядке.
""".strip()


def _chart_for_prompt(chart: dict) -> dict[str, Any]:
    return {
        "birth_date": chart["date"],
        "birth_time": chart["time"],
        "ascendant": chart["ascendant"],
        "houses": chart["houses"],
        "planets": chart["planets"],
        "aspects": chart["aspects"],
    }


def build_prompt_payload(report_type: str, chart: dict, second_chart: dict | None) -> dict[str, Any]:
    if report_type not in SECTIONS:
        raise ValueError(f"Неизвестный тип отчёта: {report_type}")
    payload: dict[str, Any] = {
        "report_type": report_type,
        "language": "ru",
        "sections": [{"title": title, "brief": brief} for title, brief in SECTIONS[report_type]],
        "primary_chart": _chart_for_prompt(chart),
        "partner_chart": _chart_for_prompt(second_chart) if second_chart else None,
        "synastry_aspects": calculate_synastry(chart, second_chart) if second_chart else [],
    }
    return payload


def _validate_content(content: Any, report_type: str) -> dict[str, Any] | None:
    if not isinstance(content, dict) or not all(isinstance(content.get(key), str) for key in ("title", "intro", "disclaimer")):
        return None
    expected_titles = [title for title, _ in SECTIONS[report_type]]
    sections = content.get("sections")
    if not isinstance(sections, list) or len(sections) != len(expected_titles):
        return None
    if [section.get("title") for section in sections] != expected_titles:
        return None
    if not all(isinstance(section.get("content"), str) and section["content"].strip() for section in sections):
        return None
    return content


async def generate_report_content(
    report_type: str, chart: dict, second_chart: dict | None = None
) -> dict[str, Any] | None:
    """Return AI content or None, allowing PDF generation to use its local fallback."""
    if not settings.ai_api_key:
        return None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            timeout=90.0,
        )
        response = await client.chat.completions.create(
            model=settings.ai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(build_prompt_payload(report_type, chart, second_chart), ensure_ascii=False),
                },
            ],
        )
        raw_content = response.choices[0].message.content
        if not raw_content:
            return None
        return _validate_content(json.loads(raw_content), report_type)
    except (ImportError, json.JSONDecodeError, TimeoutError, ValueError) as error:
        logger.warning("Не удалось получить AI-отчёт: %s", error)
        return None
    except Exception:
        logger.exception("Неожиданная ошибка генерации AI-отчёта")
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
