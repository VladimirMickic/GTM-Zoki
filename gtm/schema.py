"""The Prospect schema — the contract every pipeline stage reads and writes."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

# Separator for the parallel "; "-joined contact_name/contact_title/
# contact_linkedin/contact_emails fields — shared by gtm/hubspot.py::_split_contacts
# and gtm/output.py::build_contact_rows, the two places that split them back apart.
CONTACT_FIELD_SEP = "; "

# Locked column order for the main Google Sheet tab (docs/PLAN.md). Ends at
# community_signals — everything downstream of it (outreach_angle, the draft
# fields, qa_flag, source, date_processed, status) lives on the Contacts tab
# (gtm/output.py::CONTACT_COLUMNS) or in local state, not on the company row.
# `tier` (1/2/3) is derived from status by the Prospect.tier property, not a
# stored field — it sits right after fit_score (the score's 1/2/3 band).
SHEET_COLUMNS = [
    "company",
    "website",
    "description",
    "drone_models",
    "drone_dimensions",
    "drone_weights",
    "best_case_line",
    "us_made_ndaa",
    "fit_score",
    "tier",
    "why_fit",
    "fit_reason",
    "buying_signals",
    "key_news",
    "linkedin",
    "community_signals",
]

# status → tier band (ICP.md): priority=Tier 1, keep=Tier 2, drop=Tier 3.
# error/unscored companies have no tier (blank).
_STATUS_TIER = {"priority": "1", "keep": "2", "drop": "3"}

# 2026-07-21 (user): keep sheet cells scannable — trim the long-form cells. Full
# untrimmed detail stays in prospects.json (local state), only the sheet is capped.
_LONG_LIST_COLS = ("key_news", "buying_signals", "community_signals")
_LIST_MAX_ITEMS = 3  # top-N entries per long-list cell
_ENTRY_MAX_CHARS = 180  # per entry
_FIT_REASON_MAX_CHARS = 400


def _trim(s: str, n: int) -> str:
    """Cap a string to n chars on a word boundary, adding an ellipsis when cut."""
    s = s.strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip() + "…"


def _trim_keep_source(s: str, n: int) -> str:
    """Like _trim, but for "<text> (<url>)" entries (gtm/enrich.py::_news_line):
    trims the text, never the trailing "(url)" — a cut source link is why the
    2026-07-24 community-signals feedback read as "no sources" (the sheet cell
    was silently eating the parenthetical)."""
    s = s.strip()
    if s.endswith(")") and " (" in s:
        text, _, source = s[:-1].rpartition(" (")
        source = f" ({source})"
        budget = max(n - len(source), 0)
        return (text if len(text) <= budget else text[:budget].rsplit(" ", 1)[0].rstrip() + "…") + source
    return _trim(s, n)


class DraftSet(BaseModel):
    """One tier's outreach package: pain_points/talking_points (always
    produced — the primary, position-specific deliverable) plus a single
    2-version cold-email draft (no follow-up) when the signal is strong
    enough to write one — see gtm/draft.py::is_thin_signal. One of these per
    persona tier present at a company (gtm/persona.py::distinct_tiers_present)
    — a CFO and a director never share a draft or the same talking points."""
    pain_points: str = ""
    talking_points: str = ""
    needs_research: bool = False  # True when signal was too thin to draft a real email
    initial_subject: str = ""
    initial_body: str = ""
    initial_subject_alt: str = ""
    initial_body_alt: str = ""
    qa_flag: str = ""


class Prospect(BaseModel):
    # stage 1 — input
    company: str
    website: str
    source: str = ""
    # stage 3 — extract
    description: str = ""
    drone_models: list[str] = []
    drone_dimensions: list[str] = []  # L×W×H (folded/unfolded), per model
    drone_weights: list[str] = []
    case_evidence: str = ""  # what they ship in today (state-only, feeds fit; not a sheet column)
    us_made_ndaa: Optional[bool] = None
    hq_city: str = ""  # state-only; feeds gtm/hubspot.py company city/country properties
    hq_country: str = ""
    # stage 4 — fit
    fit_score: Optional[int] = None
    fit_reason: str = ""
    best_case_line: str = ""
    # stage 5 — contacts + enrich (state only; not in SHEET_COLUMNS — read by
    # gtm/draft.py and gtm/hubspot.py directly, and reconstructed into the
    # Contacts tab/CSV by gtm/output.py::build_contact_rows)
    contact_name: str = ""
    contact_title: str = ""
    contact_linkedin: str = ""
    contact_emails: str = ""  # "email (status)" per contact, parallel to contact_name; "-" = miss
    buying_signals: list[str] = []
    key_news: list[str] = []
    linkedin: str = ""
    community_signals: list[str] = []
    outreach_angle: str = ""
    # stage "enrich" (displacement sub-step, gtm/displace.py) — state-only, feeds
    # draft's value-prop ammo; "" / [] when no named competitor was detected.
    competitor: str = ""
    competitor_weaknesses: list[str] = []
    # stage "segment" — deterministic bucketing, feeds draft's angle choice; not a sheet column
    segment: str = ""
    # stage "draft" — one DraftSet per distinct persona tier present among this
    # company's contacts (gtm/persona.py::distinct_tiers_present). Replaces the
    # old single flat draft_*/qa_flag fields — gtm/output.py::build_contact_rows
    # picks the matching-tier entry per contact row.
    drafts_by_tier: dict[str, DraftSet] = {}
    # stage 6 — output / feedback
    date_processed: str = ""
    status: str = ""

    @property
    def tier(self) -> str:
        """1/2/3 funnel band, derived from status so it never drifts from fit.
        Read by SHEET_COLUMNS via getattr in to_sheet_row (not a stored field)."""
        return _STATUS_TIER.get(self.status, "")

    @property
    def why_fit(self) -> str:
        """One-line scannable summary for the Companies tab, so a reader gets the
        gist without opening the long fit_reason/buying_signals/key_news cells.
        Derived (not stored, like `tier`): band + score · case line · top signal."""
        band = {"1": "Strong fit", "2": "Possible fit", "3": "Dropped"}.get(self.tier, "Unscored")
        head = f"{band} ({self.fit_score}/100)" if self.fit_score is not None else band
        parts = [head]
        if self.best_case_line:
            parts.append(f"{self.best_case_line} case")
        if self.buying_signals:
            # leading clause of the top buying signal, before the em-dash rationale
            # or the parenthetical source; trimmed so the cell stays one glance.
            top = self.buying_signals[0].split(" — ")[0].split(" (")[0].strip()
            if len(top) > 90:  # trim on a word boundary, never mid-number/word
                top = top[:90].rsplit(" ", 1)[0] + "…"
            parts.append(top)
        return " · ".join(parts)

    def to_sheet_row(self) -> list[str]:
        """Render one sheet row in SHEET_COLUMNS order (lists joined, None blank)."""
        row = []
        for col in SHEET_COLUMNS:
            v = getattr(self, col)
            if v is None:
                row.append("")
            elif col == "fit_score":
                row.append(f"{v}/100")
            elif isinstance(v, bool):
                row.append("yes" if v else "no")
            elif col == "fit_reason":
                row.append(_trim(str(v), _FIT_REASON_MAX_CHARS))
            elif isinstance(v, list):
                if col in _LONG_LIST_COLS:
                    # long-form cells: top-N entries, each trimmed, one per line
                    items = [_trim_keep_source(str(x), _ENTRY_MAX_CHARS) for x in v[:_LIST_MAX_ITEMS]]
                    row.append("\n".join(items))
                else:
                    row.append("; ".join(str(x) for x in v))  # short specs stay inline
            else:
                row.append(str(v))
        return row
