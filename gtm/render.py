"""Slice 6 — fill the draft's {{tokens}} at output time, or refuse to ship the row.

Every draft prompt and company/voice-guide.md write variables as double-brace
lowercase ({{first_name}}, {{company_name}}, {{case_line}}, {{trigger_event}},
{{airframe_name}}, {{reference_customer}}, {{sender_name}}). gtm/output.py used to
substitute {FIRST_NAME} / {COMPANY} — single-brace UPPERCASE, a vocabulary nothing
in the repo emits — so the substitution was dead code and run test-batch-1 pushed
raw tokens to the live Sheet and HubSpot.

Two of those tokens have no source in the pipeline: the human who signs the email
and the customer we may name as social proof. Both come from company/outreach.md,
which ships TODO-seeded — an unfilled value leaves the token in place, and the
caller's ship gate blanks the draft rather than sending it half-filled.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from gtm.draft import fresh_signals
from gtm.schema import Prospect

OUTREACH_FILE = Path("company") / "outreach.md"

# Every variable a draft may contain (company/voice-guide.md "Email structure").
DRAFT_TOKENS = (
    "first_name",
    "company_name",
    "airframe_name",
    "case_line",
    "trigger_event",
    "reference_customer",
    "sender_name",
)

_TOKEN = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}", re.IGNORECASE)
_KEY_LINE = re.compile(r"^-\s*([a-z_]+)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^-\s*(.+?)\s*$")


class OutreachConfig(BaseModel):
    sender_name: str = ""
    sender_title: str = ""
    sender_email: str = ""
    reference_customers: list[str] = []
    fallback_reference: str = ""


def _is_todo(value: str) -> bool:
    return "todo" in value.lower()


def load_outreach_config(path: str | Path = OUTREACH_FILE) -> OutreachConfig:
    """Parse company/outreach.md. Any value containing TODO is treated as unset —
    a placeholder must behave exactly like missing data, never like a name."""
    path = Path(path)
    if not path.exists():
        return OutreachConfig()

    cfg = OutreachConfig()
    section = ""
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip().lower()
            continue
        if not stripped.startswith("-"):
            continue

        key_match = _KEY_LINE.match(stripped)
        key = key_match.group(1).lower() if key_match else ""
        value = key_match.group(2).strip() if key_match else ""

        if section.startswith("sender") and key_match:
            if _is_todo(value):
                continue
            if key == "name":
                cfg.sender_name = value
            elif key == "title":
                cfg.sender_title = value
            elif key == "email":
                cfg.sender_email = value
        elif section.startswith("approved reference"):
            bullet = _BULLET.match(stripped)
            if bullet and not _is_todo(bullet.group(1)):
                cfg.reference_customers.append(bullet.group(1))
        elif section.startswith("fallback reference") and key == "fallback" and not _is_todo(value):
            cfg.fallback_reference = value
    return cfg


def render_tokens(text: str, ctx: dict) -> str:
    """Substitute {{token}} from ctx. A token that is unknown or maps to an empty
    value is left in place on purpose: the caller's ship gate needs to see it.
    Silent blanking is how an email goes out signed by nobody."""
    def sub(m: re.Match) -> str:
        return str(ctx.get(m.group(1).lower()) or m.group(0))

    return _TOKEN.sub(sub, text or "")


def unrendered_tokens(text: str) -> list[str]:
    """Every {{...}} still standing after a render, in order of appearance."""
    return [m.group(0) for m in _TOKEN.finditer(text or "")]


def pick_reference_customer(prospect: Prospect, config: OutreachConfig, run_mates) -> str:
    """An approved reference that is neither the recipient nor another company in
    this run. The voice guide's hard rule, enforced in code rather than only in the
    QA prompt: naming one prospect as a customer to another is the worst send in
    the pipeline. Falls back to the configured category-level phrase, then "" —
    and "" leaves the token standing, which blocks the row."""
    blocked = {c.strip().lower() for c in run_mates if c and c.strip()}
    blocked.add(prospect.company.strip().lower())
    for name in config.reference_customers:
        if name.strip().lower() not in blocked:
            return name
    return config.fallback_reference


def _trigger_event(prospect: Prospect) -> str:
    """The freshest signal that may open an email, reduced to the event itself.

    Signal lines read "<what happened> — <why it matters> (<source>, <date>)"; only
    the first half belongs in a sentence. [stale]/[undated] signals are excluded by
    fresh_signals — an old event greeted as news is what run test-batch-1 sent."""
    fresh = fresh_signals(prospect)
    if not fresh:
        return ""
    event = fresh[0].split("—")[0].strip()
    return re.sub(r"\s*\([^)]*\)\s*$", "", event).strip()


def build_render_context(
    prospect: Prospect, *, first_name: str, config: OutreachConfig, run_mates
) -> dict:
    return {
        "first_name": first_name.strip() or "there",
        "company_name": prospect.company,
        "airframe_name": prospect.drone_models[0] if prospect.drone_models else "",
        "case_line": prospect.best_case_line,
        "trigger_event": _trigger_event(prospect),
        "reference_customer": pick_reference_customer(prospect, config, run_mates),
        "sender_name": config.sender_name,
    }
