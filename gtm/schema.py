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
    "fit_reason",
    "buying_signals",
    "key_news",
    "linkedin",
    "community_signals",
]

# status → tier band (ICP.md): priority=Tier 1, keep=Tier 2, drop=Tier 3.
# error/unscored companies have no tier (blank).
_STATUS_TIER = {"priority": "1", "keep": "2", "drop": "3"}


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
    # stage "segment" — deterministic bucketing, feeds draft's angle choice; not a sheet column
    segment: str = ""
    # stage "draft" — v1 (primary) variant, surfaced on the sheet
    draft_initial_subject: str = ""
    draft_initial_body: str = ""
    draft_followup_subject: str = ""
    draft_followup_body: str = ""
    # stage "draft" — v2 (alternate) variant, state-only; open drafts.json for it
    draft_initial_subject_alt: str = ""
    draft_initial_body_alt: str = ""
    draft_followup_subject_alt: str = ""
    draft_followup_body_alt: str = ""
    # stage "draft" (qa sub-step) — empty when clean, else a short unsupported-claim note
    qa_flag: str = ""
    # stage 6 — output / feedback
    date_processed: str = ""
    status: str = ""

    @property
    def tier(self) -> str:
        """1/2/3 funnel band, derived from status so it never drifts from fit.
        Read by SHEET_COLUMNS via getattr in to_sheet_row (not a stored field)."""
        return _STATUS_TIER.get(self.status, "")

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
            elif isinstance(v, list):
                # long-form cells read one-item-per-line; short specs stay inline
                sep = "\n" if col in ("key_news", "buying_signals", "community_signals") else "; "
                row.append(sep.join(str(x) for x in v))
            else:
                row.append(str(v))
        return row
