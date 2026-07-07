---
name: daily-briefing
description: "Turns exported email + calendar JSON into a self-contained HTML briefing with overview stats, today/tomorrow calendar, open action items, and carry-over to-dos from the previous briefing. Works on synthetic sample data in examples/; live email access is out of scope for this repo. Use when the user asks for a daily briefing or morning stand-up from local exported data."
---

# daily-briefing

Local, deterministic morning briefing from JSON exports. No LLM call, no external service, stdlib-only Python. Reads an emails/calendar JSON export, extracts action items via keyword patterns, cross-references yesterday's state to figure out what got done, and writes one self-contained HTML file with inline CSS.

## When to invoke

- The user asks for a "daily briefing", "morning stand-up", or "what's on my plate today".
- The user hands you exported email + calendar JSON (a directory or one file).
- You have a previous briefing's `.state.json` sidecar and want to carry unfinished items forward.

Live email access (Gmail/Outlook APIs, IMAP) is deliberately out of scope for this repo. The skill runs against the synthetic sample under `examples/sample_briefing_data/`, and against any real export you produce yourself in the same shape.

## Input shape

Two JSON files, or one combined file. Either passed as a single-file `--input path.json` or a directory containing them.

`emails.json`:
```json
{
  "emails": [
    {
      "from": "Jamie Ortiz <jamie.ortiz@northwood-holdings.example>",
      "subject": "Q3 planning: your input on the dashboards roadmap",
      "body": "Could you please review the attached draft and send feedback by 2026-07-11?",
      "received_at": "2026-07-06T14:03:00",
      "read": false
    }
  ]
}
```

`calendar.json`:
```json
{
  "calendar": [
    {
      "title": "Weekly stand-up",
      "start": "2026-07-07T09:00:00",
      "end": "2026-07-07T09:30:00",
      "attendees": ["Jamie Ortiz", "Priya Nair"],
      "notes": ""
    }
  ]
}
```

Timestamps are ISO 8601 (with or without timezone).

## Output

A single `briefing.html` file. Inline CSS, no external assets. Sections in order:

1. **Overview stats**: emails today, unread count, meetings today, meetings tomorrow, open action items.
2. **Today**: calendar events for the "as-of" date, sorted by start time.
3. **Tomorrow**: same for the next day.
4. **Stuff to do**: open action items extracted from the emails plus any carried forward from the previous state. Multi-day / week-spanning items are flagged.
5. **Stuff taken care of**: items that appeared in the previous state but no longer surface today — treated as completed.
6. **Emails**: one-line summaries of the day's emails.

A companion `briefing.state.json` is written next to the HTML with the raw action-item list. Feed that back in as `--previous-state` on the next run to get carry-forward.

## Usage

```
python .claude/skills/daily-briefing/briefing.py \
  --input examples/sample_briefing_data \
  --output /tmp/briefing.html \
  --previous-state examples/sample_briefing_data/previous_state.json \
  --as-of 2026-07-07
```

Flags:
- `--input PATH` (required): file or directory of JSON.
- `--output PATH` (required): where to write the HTML. The `.state.json` sidecar is written alongside.
- `--previous-state PATH` (optional): the previous run's `.state.json`. Enables the "stuff taken care of" section and carry-forward.
- `--as-of YYYY-MM-DD` (optional): pretend today is this date. Defaults to the system date. Useful for reproducible runs against fixed sample data.

## Design decisions worth noticing

- **No LLM**. The whole flow is deterministic: keyword matches for action items, regex for due-date extraction, ISO-timestamp comparisons for calendar filtering. Reproducible on the same input every time, fast, no API dependency.
- **State is JSON, not scraped HTML**. The sidecar `.state.json` is the authoritative carry-forward record. The HTML is human-readable output; treating it as machine-readable state would be fragile as the template evolves.
- **Multi-day flag lives in the item**. Items with a due date three or more days out (or referencing "end of week" / "next week") are tagged; the template renders them with a badge so a week-spanning obligation stays visible instead of being buried in a single-day view.
- **The driver trusts `--as-of` and nothing else**. Every date-relative decision (today, tomorrow, is-multi-day) derives from that one value. Reproducibility for testing beats convenience of `datetime.now()` as the default.

## Action-item extraction

An email is treated as an action item if its subject or body contains any of: `please review`, `action required`, `action needed`, `your input`, `asap`, `urgent`, `deadline`, `due by`, `by end of`, `eod`, `please respond`, `please reply`, `please confirm`, `please send`.

Due dates are extracted with a small regex vocabulary: ISO dates (`2026-07-11`), US-format dates (`7/11`, `7/11/2026`), and phrases (`by Friday`, `by next week`, `by EOW`).

Refinement is easy: edit `ACTION_KEYWORDS` and `DATE_PATTERNS` in `briefing.py`.
