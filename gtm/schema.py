"""The Prospect schema — the contract every pipeline stage reads and writes."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

# Locked column order for the Google Sheet (docs/PLAN.md).
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
    "fit_reason",
    "buying_signals",
    "key_news",
    "linkedin",
    "reddit_signal",
    "outreach_angle",
    "draft_initial_subject",
    "draft_initial_body",
    "draft_followup_subject",
    "draft_followup_body",
    "contact_name",
    "contact_title",
    "contact_linkedin",
    "contact_emails",
    "qa_flag",
    "source",
    "date_processed",
    "status",
]


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
    # stage 5 — contacts + enrich
    contact_name: str = ""
    contact_title: str = ""
    contact_linkedin: str = ""
    contact_emails: str = ""  # "email (status)" per contact, parallel to contact_name; "-" = miss
    buying_signals: list[str] = []
    key_news: list[str] = []
    linkedin: str = ""
    reddit_signal: str = ""
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
                sep = "\n" if col in ("key_news", "buying_signals") else "; "
                row.append(sep.join(str(x) for x in v))
            else:
                row.append(str(v))
        return row
