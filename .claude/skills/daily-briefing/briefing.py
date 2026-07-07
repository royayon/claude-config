#!/usr/bin/env python3
"""daily-briefing: turn exported email + calendar JSON into a self-contained
HTML briefing with stats, today/tomorrow calendar, action items, and
carry-forward of yesterday's open items.

Usage:
    python briefing.py \\
        --input examples/sample_briefing_data \\
        --output /tmp/briefing.html \\
        --previous-state examples/sample_briefing_data/previous_state.json \\
        --as-of 2026-07-07

Stdlib only. No LLM call, no network. Deterministic on the same input.

Design notes are in SKILL.md. The short version:
    - Action items are keyword-triggered; refine ACTION_KEYWORDS below.
    - Due dates come from a small regex vocabulary; refine DATE_PATTERNS.
    - Carry-forward reads a JSON sidecar; the HTML is human-readable output,
      not machine state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as html_lib
import json
import re
import sys
from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "templates" / "briefing.html"

ACTION_KEYWORDS = (
    "please review", "action required", "action needed", "your input",
    "asap", "urgent", "deadline", "due by", "by end of", "eod",
    "please respond", "please reply", "please confirm", "please send",
)

# Negation prefixes that flip a keyword from action-required to no-action.
# Allows up to one intervening word so "without any deadline" is still caught.
# Skips substrings like "no action needed", "not urgent", "no more deadlines".
_NEGATION_RE = re.compile(
    r"\b(no|not|without|n't)(?:\s+\w+)?\s+$", re.IGNORECASE
)

DATE_PATTERNS = (
    (re.compile(r"\bby\s+(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE), "iso"),
    (re.compile(r"\bdue\s+(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE), "iso"),
    (re.compile(r"\bbefore\s+(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE), "iso"),
    (re.compile(r"\bby\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b"), "us"),
    (re.compile(
        r"\bby\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
        re.IGNORECASE), "weekday"),
    (re.compile(
        r"\b(end\s+of\s+(?:the\s+)?week|next\s+week|EOW|EOD)\b",
        re.IGNORECASE), "phrase"),
)

MULTIDAY_THRESHOLD_DAYS = 3


# ---- Input --------------------------------------------------------------


def load_input(path: Path) -> dict:
    """Accept a directory of JSON files or a single JSON file. Aggregates
    'emails' and 'calendar' arrays across all files found."""
    data: dict = {"emails": [], "calendar": []}
    if path.is_file():
        blob = json.loads(path.read_text(encoding="utf-8"))
        data["emails"].extend(blob.get("emails") or [])
        data["calendar"].extend(blob.get("calendar") or [])
        return data
    if path.is_dir():
        for f in sorted(path.glob("*.json")):
            if f.name == "previous_state.json":
                continue
            try:
                blob = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ValueError(f"{f}: JSON parse failed: {e}") from e
            data["emails"].extend(blob.get("emails") or [])
            data["calendar"].extend(blob.get("calendar") or [])
        return data
    raise FileNotFoundError(path)


def parse_dt(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ---- Extraction --------------------------------------------------------


def find_due_date(text: str, as_of: dt.date) -> str | None:
    """Best-effort due-date extraction. Returns an ISO date, or the raw
    phrase if it cannot be resolved to a concrete date."""
    for regex, kind in DATE_PATTERNS:
        m = regex.search(text)
        if not m:
            continue
        hit = m.group(1)
        if kind == "iso":
            try:
                return dt.date.fromisoformat(hit).isoformat()
            except ValueError:
                return hit
        if kind == "us":
            for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m/%d"):
                try:
                    d = dt.datetime.strptime(hit, fmt).date()
                    if fmt == "%m/%d":
                        d = d.replace(year=as_of.year)
                    return d.isoformat()
                except ValueError:
                    continue
            return hit
        if kind in ("weekday", "phrase"):
            return hit
    return None


def one_line(text: str, max_len: int = 140) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def is_multi_day(item: dict, as_of: dt.date) -> bool:
    due = item.get("due")
    if not due:
        return False
    if re.search(r"end\s+of\s+(?:the\s+)?week|next\s+week|EOW", due, re.IGNORECASE):
        return True
    try:
        d = dt.date.fromisoformat(due)
    except ValueError:
        return False
    return (d - as_of).days >= MULTIDAY_THRESHOLD_DAYS


def _has_unnegated_keyword(text: str) -> bool:
    """True if any ACTION_KEYWORDS occurrence is not immediately preceded
    by a negator (no / not / without / n't)."""
    lower = text.lower()
    for kw in ACTION_KEYWORDS:
        start = 0
        while True:
            i = lower.find(kw, start)
            if i < 0:
                break
            prefix = lower[max(0, i - 24):i]
            if not _NEGATION_RE.search(prefix):
                return True
            start = i + 1
    return False


def extract_action_items(emails: list[dict], as_of: dt.date) -> list[dict]:
    items: list[dict] = []
    for e in emails:
        content = (
            (e.get("subject") or "") + "\n" + (e.get("body") or "")
        )
        if not _has_unnegated_keyword(content):
            continue
        due = find_due_date(content, as_of)
        item = {
            "source": e.get("from") or "unknown",
            "subject": e.get("subject") or "",
            "description": one_line(e.get("body") or ""),
            "due": due,
        }
        item["multi_day"] = is_multi_day(item, as_of)
        items.append(item)
    return items


def item_key(item: dict) -> tuple:
    return (item.get("source") or "", item.get("subject") or "")


def carry_forward(previous: list[dict], current: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (open_now, taken_care_of).

    open_now = current items, tagged 'carried' if they were also in previous.
    taken_care_of = previous items whose key does not appear in current.
    """
    curr_keys = {item_key(i) for i in current}
    prev_keys = {item_key(p) for p in previous}
    open_now: list[dict] = []
    for item in current:
        merged = dict(item)
        merged["carried"] = item_key(item) in prev_keys
        open_now.append(merged)
    taken_care_of = [p for p in previous if item_key(p) not in curr_keys]
    return open_now, taken_care_of


def filter_calendar(events: list[dict], target: dt.date) -> list[dict]:
    out: list[dict] = []
    for e in events:
        start = parse_dt(e.get("start"))
        if start and start.date() == target:
            out.append(e)
    out.sort(key=lambda e: parse_dt(e.get("start")) or dt.datetime.min)
    return out


# ---- Rendering ---------------------------------------------------------


def esc(s: object) -> str:
    return html_lib.escape("" if s is None else str(s), quote=True)


def render_stats(emails_today: int, unread: int, meet_today: int,
                 meet_tomorrow: int, open_items: int) -> str:
    cells = [
        (emails_today, "Emails today"),
        (unread, "Unread"),
        (meet_today, "Meetings today"),
        (meet_tomorrow, "Meetings tomorrow"),
        (open_items, "Open action items"),
    ]
    return "\n".join(
        f'  <div class="stat"><div class="num">{n}</div>'
        f'<div class="label">{esc(lbl)}</div></div>'
        for n, lbl in cells
    )


def _fmt_time(iso: str) -> str:
    d = parse_dt(iso)
    return d.strftime("%H:%M") if d else esc(iso)


def render_calendar(events: list[dict]) -> str:
    if not events:
        return '<div class="empty">Nothing on the calendar.</div>'
    parts = ['<ul class="calendar">']
    for e in events:
        start = _fmt_time(e.get("start") or "")
        end = _fmt_time(e.get("end") or "")
        attendees = ", ".join(e.get("attendees") or [])
        parts.append(
            f'  <li><span class="time">{start}&ndash;{end}</span> '
            f'<span class="event-title">{esc(e.get("title") or "")}</span>'
        )
        if attendees:
            parts.append(f'    <div class="attendees">{esc(attendees)}</div>')
        parts.append("  </li>")
    parts.append("</ul>")
    return "\n".join(parts)


def render_todo(items: list[dict]) -> str:
    if not items:
        return '<div class="empty">No open action items.</div>'
    parts = ['<ul class="todo">']
    for item in items:
        badges = ""
        if item.get("multi_day"):
            badges += ' <span class="badge multiday">multi-day</span>'
        if item.get("carried"):
            badges += ' <span class="badge carried">carried over</span>'
        due = f' &middot; due {esc(item.get("due"))}' if item.get("due") else ""
        parts.append(
            f'  <li>'
            f'<div class="subject">{esc(item.get("subject"))}{badges}</div>'
            f'<div class="meta">{esc(item.get("source"))}{due}</div>'
            f'<div class="desc">{esc(item.get("description"))}</div>'
            f'</li>'
        )
    parts.append("</ul>")
    return "\n".join(parts)


def render_done(items: list[dict]) -> str:
    if not items:
        return '<div class="empty">Nothing to celebrate yet.</div>'
    parts = ['<ul class="done">']
    for item in items:
        parts.append(
            f'  <li>'
            f'<div class="subject">{esc(item.get("subject"))}'
            f' <span class="badge done">done</span></div>'
            f'<div class="meta">{esc(item.get("source"))}</div>'
            f'</li>'
        )
    parts.append("</ul>")
    return "\n".join(parts)


def render_emails(emails: list[dict]) -> str:
    if not emails:
        return '<div class="empty">No emails today.</div>'
    parts = ['<ul class="emails">']
    for e in emails:
        parts.append(
            f'  <li>'
            f'<span class="from">{esc(e.get("from"))}</span>'
            f'<span class="subject">{esc(e.get("subject"))}</span>'
            f'<div class="summary">{esc(one_line(e.get("body") or ""))}</div>'
            f'</li>'
        )
    parts.append("</ul>")
    return "\n".join(parts)


def render(template: str, replacements: dict) -> str:
    out = template
    for key, value in replacements.items():
        out = out.replace("{{" + key + "}}", value)
    return out


# ---- Main --------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, type=Path,
                        help="File or directory of JSON exports")
    parser.add_argument("--output", required=True, type=Path,
                        help="Where to write the HTML")
    parser.add_argument("--previous-state", type=Path,
                        help="Previous run's .state.json for carry-forward")
    parser.add_argument("--as-of", type=str,
                        help="Treat this ISO date (YYYY-MM-DD) as today")
    args = parser.parse_args(argv)

    if args.as_of:
        try:
            as_of = dt.date.fromisoformat(args.as_of)
        except ValueError:
            print(f"error: bad --as-of value: {args.as_of}", file=sys.stderr)
            return 3
    else:
        as_of = dt.date.today()
    tomorrow = as_of + dt.timedelta(days=1)

    try:
        data = load_input(args.input)
    except FileNotFoundError:
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3

    all_emails = data["emails"]
    calendar = data["calendar"]

    emails_today = [
        e for e in all_emails
        if (d := parse_dt(e.get("received_at"))) and d.date() == as_of
    ]
    unread_today = sum(1 for e in emails_today if not e.get("read"))

    today_events = filter_calendar(calendar, as_of)
    tomorrow_events = filter_calendar(calendar, tomorrow)

    current_items = extract_action_items(all_emails, as_of)

    previous_items: list[dict] = []
    if args.previous_state:
        try:
            payload = json.loads(args.previous_state.read_text(encoding="utf-8"))
            previous_items = payload.get("action_items") or []
        except (OSError, json.JSONDecodeError) as e:
            print(f"warning: could not read previous state: {e}", file=sys.stderr)

    open_items, taken_care_of = carry_forward(previous_items, current_items)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "DATE": as_of.isoformat(),
        "DATE_LONG": as_of.strftime("%A, %d %B %Y"),
        "STATS_HTML": render_stats(
            len(emails_today), unread_today, len(today_events),
            len(tomorrow_events), len(open_items),
        ),
        "TODAY_HTML": render_calendar(today_events),
        "TOMORROW_HTML": render_calendar(tomorrow_events),
        "TODO_HTML": render_todo(open_items),
        "DONE_HTML": render_done(taken_care_of),
        "EMAILS_HTML": render_emails(emails_today),
    }
    html = render(template, replacements)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")

    # Sidecar state for the next run's carry-forward.
    state_path = args.output.with_suffix(".state.json")
    state = {
        "as_of": as_of.isoformat(),
        "action_items": [
            {k: v for k, v in item.items() if k != "carried"}
            for item in open_items
        ],
    }
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"[daily-briefing] wrote {args.output} "
        f"({len(emails_today)} emails, {len(today_events)} today, "
        f"{len(open_items)} open, {len(taken_care_of)} done), "
        f"state -> {state_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
