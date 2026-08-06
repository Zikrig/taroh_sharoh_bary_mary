#!/usr/bin/env python3
"""Render AI payload JSON into a readable standalone HTML file.

Usage:
  python scripts/json_to_html.py payload.json
  python scripts/json_to_html.py a.json b.json -o out.html
  python scripts/json_to_html.py docker.log --from-logs
  type payload.json | python scripts/json_to_html.py -
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUEST_LINE_RE = re.compile(
    r"AI user payload,\s*sections=.*?:\s*(\{.*\})\s*$",
    re.M,
)
RESPONSE_MARK_RE = re.compile(
    r"AI raw response,\s*sections=.*?:\s*",
    re.M,
)
DOCKER_PREFIX_RE = re.compile(r"^(?:[\w-]+\s+\|\s+)?(.*)$")
SECTION_ORDER = (
    "Введение",
    "Солнечный знак",
    "Лунный знак",
    "Асцендент",
    "Личностные планеты",
    "Социальные планеты",
    "Высшие планеты",
    "Дома гороскопа",
    "Ключевые аспекты",
    "Кармические задачи",
    "Любовь и отношения",
    "Карьера и призвание",
    "Здоровье и энергия",
    "Таланты и способности",
    "Заключение",
)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def load_json_text(raw: str) -> Any:
    return json.loads(raw)


def strip_docker_prefixes(text: str) -> str:
    lines = []
    for line in text.splitlines():
        match = DOCKER_PREFIX_RE.match(line)
        lines.append(match.group(1) if match else line)
    return "\n".join(lines)


def extract_requests(text: str) -> list[Any]:
    return [json.loads(match.group(1)) for match in REQUEST_LINE_RE.finditer(text)]


def extract_responses(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    payloads: list[Any] = []
    for match in RESPONSE_MARK_RE.finditer(text):
        chunk = text[match.end() :]
        brace = chunk.find("{")
        if brace < 0:
            continue
        try:
            obj, _ = decoder.raw_decode(chunk[brace:])
        except json.JSONDecodeError:
            continue
        payloads.append(obj)
    return payloads


def merge_by_sections(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    if not payloads:
        raise ValueError("No payloads to merge")
    merged = dict(payloads[0])
    section_map: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        for section in payload.get("sections") or []:
            title = section.get("title")
            if isinstance(title, str) and title:
                section_map[title] = section
    ordered = [section_map[title] for title in SECTION_ORDER if title in section_map]
    for title, section in section_map.items():
        if title not in {item["title"] for item in ordered}:
            ordered.append(section)
    merged["sections"] = ordered
    return merged


def is_response_payload(payload: dict[str, Any]) -> bool:
    sections = payload.get("sections") or []
    if not sections:
        return False
    first = sections[0]
    return isinstance(first, dict) and "content" in first and "primary_chart" not in payload


def read_inputs(
    paths: list[str],
    from_logs: bool,
    kind: str,
    merge: bool,
) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for path in paths:
        if path == "-":
            text = sys.stdin.read()
            label = "stdin"
        else:
            text = Path(path).read_text(encoding="utf-8")
            label = Path(path).name

        if from_logs:
            clean = strip_docker_prefixes(text)
            if kind == "request":
                payloads = extract_requests(clean)
                item_label = "request"
            elif kind == "response":
                payloads = extract_responses(clean)
                item_label = "response"
            else:
                raise SystemExit("--kind must be request or response with --from-logs")
            if not payloads:
                raise SystemExit(f"No {kind} JSON found in {label}")
            if merge:
                items.append((item_label, merge_by_sections(payloads)))
            else:
                for index, payload in enumerate(payloads, start=1):
                    items.append((f"{item_label} #{index}", payload))
            continue

        text = text.strip()
        if not text:
            raise SystemExit(f"Empty input: {label}")

        match = REQUEST_LINE_RE.search(text)
        if match:
            payload = json.loads(match.group(1))
        else:
            payload = load_json_text(text)
        items.append((label, payload))
    return items


def render_meta(payload: dict[str, Any]) -> str:
    rows = [
        ("Тип отчёта", payload.get("report_type")),
        ("Язык", payload.get("language")),
    ]
    return "".join(
        f"<div class='kv'><span>{esc(k)}</span><strong>{esc(v)}</strong></div>"
        for k, v in rows
        if v is not None
    )


def render_sections(sections: list[dict[str, Any]] | None, *, as_response: bool) -> str:
    if not sections:
        return "<p class='muted'>Нет разделов</p>"
    cards = []
    for section in sections:
        if as_response:
            refs = section.get("references") or []
            refs_html = ""
            if refs:
                items = "".join(f"<li>{esc(ref)}</li>" for ref in refs)
                refs_html = f"<ul class='refs'>{items}</ul>"
            cards.append(
                "<article class='card wide'>"
                f"<h3>{esc(section.get('title'))}</h3>"
                f"<p class='content'>{esc(section.get('content'))}</p>"
                f"{refs_html}"
                "</article>"
            )
        else:
            cards.append(
                "<article class='card'>"
                f"<h3>{esc(section.get('title'))}</h3>"
                f"<p class='brief'>{esc(section.get('brief'))}</p>"
                f"<p class='guidance'><span>Guidance</span>{esc(section.get('guidance'))}</p>"
                "</article>"
            )
    css = "stack" if as_response else "grid"
    return f"<div class='{css}'>{''.join(cards)}</div>"


def render_planet_rows(planets: dict[str, Any] | None) -> str:
    if not planets:
        return ""
    rows = []
    for name, data in planets.items():
        rows.append(
            "<tr>"
            f"<td>{esc(name)}</td>"
            f"<td>{esc(data.get('sign'))}</td>"
            f"<td>{esc(data.get('degree'))}°</td>"
            f"<td>{esc(data.get('house'))}</td>"
            f"<td>{esc(data.get('longitude'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Планета</th><th>Знак</th><th>Градус</th><th>Дом</th><th>Долгота</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_aspects(aspects: list[dict[str, Any]] | None, title: str = "Аспекты") -> str:
    if not aspects:
        return f"<h3>{esc(title)}</h3><p class='muted'>Нет аспектов</p>"
    rows = []
    for aspect in aspects:
        rows.append(
            "<tr>"
            f"<td>{esc(aspect.get('first'))}</td>"
            f"<td>{esc(aspect.get('type'))}</td>"
            f"<td>{esc(aspect.get('second'))}</td>"
            f"<td>{esc(aspect.get('angle'))}°</td>"
            f"<td>{esc(aspect.get('orb'))}</td>"
            "</tr>"
        )
    return (
        f"<h3>{esc(title)}</h3>"
        "<table><thead><tr>"
        "<th>Первая</th><th>Тип</th><th>Вторая</th><th>Угол</th><th>Орб</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_chart(chart: dict[str, Any] | None, title: str) -> str:
    if not chart:
        return (
            f"<section class='block'><h2>{esc(title)}</h2>"
            "<p class='muted'>Нет данных</p></section>"
        )

    asc = chart.get("ascendant") or {}
    approx = chart.get("time_is_approximate")
    approx_label = "да" if approx else "нет" if approx is not None else "—"

    meta = [
        ("Дата", chart.get("birth_date") or chart.get("date")),
        ("Время (лок.)", chart.get("birth_time_local") or chart.get("time")),
        ("Время (UTC)", chart.get("birth_time_utc") or chart.get("utc_time")),
        ("Часовой пояс", chart.get("timezone")),
        ("Время приблизительное", approx_label),
        ("Асцендент", asc.get("sign")),
        ("ASC долгота", asc.get("longitude")),
    ]
    meta_html = "".join(
        f"<div class='kv'><span>{esc(k)}</span><strong>{esc(v)}</strong></div>"
        for k, v in meta
        if v is not None and v != "—"
    )

    houses = chart.get("houses") or []
    houses_html = ""
    if houses:
        chips = "".join(
            f"<span class='chip'><b>{i}</b>{esc(value)}</span>"
            for i, value in enumerate(houses, start=1)
        )
        houses_html = f"<h3>Дома</h3><div class='chips'>{chips}</div>"

    return (
        f"<section class='block'><h2>{esc(title)}</h2>"
        f"<div class='kv-grid'>{meta_html}</div>"
        f"{render_planet_rows(chart.get('planets'))}"
        f"{houses_html}"
        f"{render_aspects(chart.get('aspects'))}"
        "</section>"
    )


def render_facts(facts: list[str] | None) -> str:
    if not facts:
        return "<p class='muted'>Нет фактов</p>"
    items = "".join(f"<li>{esc(fact)}</li>" for fact in facts)
    return f"<ol class='facts'>{items}</ol>"


def render_career_hints(hints: dict[str, Any] | None) -> str:
    if not hints:
        return "<p class='muted'>Нет подсказок</p>"

    parts = []
    note = hints.get("important")
    if note:
        parts.append(f"<p class='note'>{esc(note)}</p>")

    houses = hints.get("active_house_professions") or []
    if houses:
        cards = []
        for item in houses:
            examples = ", ".join(item.get("profession_examples") or [])
            cards.append(
                "<article class='card compact'>"
                f"<h3>Дом {esc(item.get('house'))}</h3>"
                f"<p>{esc(item.get('themes'))}</p>"
                f"<p class='muted'>{esc(examples)}</p>"
                "</article>"
            )
        parts.append(f"<h3>Акцентные дома</h3><div class='grid'>{''.join(cards)}</div>")

    talents = hints.get("planet_talent_hints") or []
    if talents:
        rows = []
        for item in talents:
            examples = ", ".join(item.get("talent_examples") or [])
            rows.append(
                "<tr>"
                f"<td>{esc(item.get('planet'))}</td>"
                f"<td>{esc(item.get('sign'))}</td>"
                f"<td>{esc(examples)}</td>"
                f"<td>{esc(item.get('work_style'))}</td>"
                "</tr>"
            )
        parts.append(
            "<h3>Таланты планет</h3>"
            "<table><thead><tr>"
            "<th>Планета</th><th>Знак</th><th>Таланты</th><th>Стиль работы</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )

    return "".join(parts)


def render_payload(label: str, payload: dict[str, Any], index: int) -> str:
    section_titles = [
        s.get("title") for s in (payload.get("sections") or []) if isinstance(s, dict)
    ]
    subtitle = ", ".join(str(t) for t in section_titles if t)
    as_response = is_response_payload(payload)
    kind = "Ответ AI" if as_response else "Запрос к AI"

    extras = ""
    if not as_response:
        extras = f"""
  {render_chart(payload.get("primary_chart"), "Карта 1 (primary)")}
  {render_chart(payload.get("partner_chart"), "Карта 2 (partner)")}

  <section class="block">
    {render_aspects(payload.get("synastry_aspects"), "Синастрия")}
  </section>

  <section class="block">
    <h2>Allowed facts</h2>
    {render_facts(payload.get("allowed_facts"))}
  </section>

  <section class="block">
    <h2>Карьера и таланты</h2>
    {render_career_hints(payload.get("career_and_talent_hints"))}
  </section>
"""

    return f"""
<section class="payload" id="payload-{index}">
  <header class="payload-head">
    <div>
      <p class="eyebrow">{esc(label)}</p>
      <h1>{esc(kind)}</h1>
      <p class="subtitle">{esc(subtitle)}</p>
    </div>
    <div class="kv-grid">{render_meta(payload)}</div>
  </header>

  <section class="block">
    <h2>Разделы</h2>
    {render_sections(payload.get("sections"), as_response=as_response)}
  </section>
  {extras}
</section>
"""


CSS = """
:root {
  --bg: #f4efe6;
  --ink: #1f1a17;
  --muted: #6d6258;
  --line: #d8cfc2;
  --card: #fffaf3;
  --accent: #8b3a2b;
  --chip: #ebe2d6;
  --note: #fff1d6;
  --shadow: 0 10px 30px rgba(40, 28, 18, 0.08);
  --radius: 18px;
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(circle at top left, rgba(139, 58, 43, 0.08), transparent 40%),
    linear-gradient(180deg, #f7f2ea 0%, var(--bg) 100%);
  line-height: 1.5;
}
.page {
  width: min(1100px, calc(100% - 2rem));
  margin: 2rem auto 4rem;
}
.toc {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.85rem 0;
  margin-bottom: 1.5rem;
  background: rgba(244, 239, 230, 0.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line);
}
.toc a {
  color: var(--ink);
  text-decoration: none;
  padding: 0.35rem 0.75rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--card);
  font-size: 0.92rem;
}
.payload {
  margin-bottom: 3rem;
  padding: 1.5rem;
  background: rgba(255, 250, 243, 0.72);
  border: 1px solid var(--line);
  border-radius: calc(var(--radius) + 6px);
  box-shadow: var(--shadow);
}
.payload-head {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 1.5rem;
  margin-bottom: 1.5rem;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid var(--line);
}
.eyebrow {
  margin: 0 0 0.35rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.75rem;
  color: var(--muted);
}
h1, h2, h3 { margin: 0 0 0.6rem; line-height: 1.2; }
h1 { font-size: 2rem; }
h2 { font-size: 1.35rem; margin-top: 0.2rem; }
h3 { font-size: 1.05rem; }
.subtitle { margin: 0; color: var(--muted); }
.block { margin: 1.75rem 0; }
.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem;
}
.kv {
  padding: 0.75rem 0.9rem;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
}
.kv span {
  display: block;
  color: var(--muted);
  font-size: 0.8rem;
  margin-bottom: 0.2rem;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.9rem;
}
.stack {
  display: grid;
  gap: 0.9rem;
}
.card {
  padding: 1rem 1.1rem;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
.card.wide .content {
  margin: 0.4rem 0 0.8rem;
  white-space: pre-wrap;
}
.refs {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--muted);
  font-size: 0.92rem;
}
.card.compact p { margin: 0.35rem 0; }
.brief { margin: 0 0 0.75rem; color: var(--muted); }
.guidance {
  margin: 0;
  padding-top: 0.75rem;
  border-top: 1px dashed var(--line);
  font-size: 0.95rem;
}
.guidance span {
  display: block;
  margin-bottom: 0.25rem;
  color: var(--accent);
  font-size: 0.78rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.75rem 0 1.25rem;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
}
th, td {
  padding: 0.65rem 0.75rem;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
th {
  background: #f0e7da;
  font-size: 0.85rem;
  color: var(--muted);
  font-weight: 600;
}
tr:last-child td { border-bottom: none; }
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0.75rem 0 1.25rem;
}
.chip {
  display: inline-flex;
  gap: 0.4rem;
  align-items: baseline;
  padding: 0.35rem 0.65rem;
  background: var(--chip);
  border-radius: 999px;
  font-size: 0.9rem;
}
.chip b { color: var(--accent); }
.facts {
  columns: 2;
  gap: 1.5rem;
  margin: 0.5rem 0 0;
  padding-left: 1.2rem;
}
.facts li { margin: 0.25rem 0; break-inside: avoid; }
.note {
  padding: 0.9rem 1rem;
  background: var(--note);
  border: 1px solid #ead7a8;
  border-radius: 14px;
}
.muted { color: var(--muted); }
@media (max-width: 800px) {
  .payload-head { grid-template-columns: 1fr; }
  .facts { columns: 1; }
  .page { width: min(100% - 1.2rem, 1100px); margin-top: 1rem; }
}
"""


def build_html(items: list[tuple[str, Any]]) -> str:
    bodies = []
    toc = []
    for index, (label, payload) in enumerate(items, start=1):
        if not isinstance(payload, dict):
            raise SystemExit(f"{label}: root JSON must be an object")
        toc.append(f'<a href="#payload-{index}">#{index} · {esc(label)}</a>')
        bodies.append(render_payload(label, payload, index))

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI payload renders</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="page">
    <nav class="toc">{''.join(toc)}</nav>
    {''.join(bodies)}
  </div>
</body>
</html>
"""


def default_output(inputs: list[str]) -> Path:
    if len(inputs) == 1 and inputs[0] != "-":
        return Path(inputs[0]).with_suffix(".html")
    return Path("payload_preview.html")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert AI payload JSON into a readable HTML page."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="JSON files, log files, or '-' for stdin",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path (default: <input>.html or payload_preview.html)",
    )
    parser.add_argument(
        "--from-logs",
        action="store_true",
        help="Extract AI JSON from docker/log text",
    )
    parser.add_argument(
        "--kind",
        choices=("request", "response"),
        default="request",
        help="With --from-logs: extract request or response JSON",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="With --from-logs: merge batches into one document",
    )
    args = parser.parse_args()

    items = read_inputs(
        args.inputs,
        from_logs=args.from_logs,
        kind=args.kind,
        merge=args.merge,
    )
    html_text = build_html(items)
    out = Path(args.output) if args.output else default_output(args.inputs)
    out.write_text(html_text, encoding="utf-8")
    print(f"Wrote {out.resolve()} ({len(items)} payload(s))")


if __name__ == "__main__":
    main()
