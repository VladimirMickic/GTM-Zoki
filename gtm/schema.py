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
    "contact_name",
    "contact_title",
    "contact_linkedin",
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
    us_made_ndaa: Optional[bool] = None
    # stage 4 — fit
    fit_score: Optional[int] = None
    fit_reason: str = ""
    best_case_line: str = ""
    # stage 5 — contacts + enrich
    contact_name: str = ""
    contact_title: str = ""
    contact_linkedin: str = ""
    buying_signals: list[str] = []
    key_news: list[str] = []
    linkedin: str = ""
    reddit_signal: str = ""
    outreach_angle: str = ""
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
