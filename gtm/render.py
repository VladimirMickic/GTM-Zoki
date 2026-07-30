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
    Silent blanking is how an email goes out signed by nobody.

    A fill landing at a sentence start is capitalized. Drafts are written around
    {{reference_customer}} holding a company name, which is already capitalized — the
    category fallback ("a defense sUAS maker we work with") is not, and run us-drone-19
    rendered "US-made. a defense sUAS maker we work with orders..." into the live sheet
    (2026-07-29)."""
    def sub(m: re.Match) -> str:
        value = ctx.get(m.group(1).lower())
        if not value:
            return m.group(0)
        value = str(value)
        before = text[: m.start()].rstrip()
        if not before or before[-1] in ".?!":
            value = value[0].upper() + value[1:]
        return value

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
    """The noun phrase that fills {{trigger_event}} — Prospect.trigger_phrase, written by
    the signals stage, or "" when there is none.

    Deliberately does NOT derive one from buying_signals. Those are verb-led clauses
    carrying a source and a "why it matters" half ("Awarded an Air Force Phase Three
    contract to test DroneDog and ground robots networked into a single inspection
    system"), and the token slots into a possessive: "Saw {{company_name}}'s ... —
    congrats." Run us-drone-19 pushed that whole clause into the live sheet (2026-07-29).
    A heuristic normalizer was tried and rejected the same day — measured against every
    stored run it mangled roughly half the corpus ("Saw X's n Air Force Phase Three
    contract", "Saw X's Country of origin", "Saw X's Red Cat Secures $1 Million Contract").
    Reducing a clause to a phrase is judgment, so the signals stage does it; "" here leaves
    the token standing and the ship gate blocks the row, which beats broken English.
    """
    if not prospect.trigger_phrase.strip():
        return ""
    # A trigger only ever opens on something fresh. A phrase left behind after the signal
    # it came from went [stale] must not still open an email.
    return prospect.trigger_phrase.strip() if fresh_signals(prospect) else ""


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
