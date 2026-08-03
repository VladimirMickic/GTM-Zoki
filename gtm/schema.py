"""The Prospect schema — the contract every pipeline stage reads and writes."""
from __future__ import annotations

import re
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
    "headcount",
    "community_signals",
]

# status → tier band (ICP.md): priority=Tier 1, keep=Tier 2, drop=Tier 3.
# error/unscored companies have no tier (blank).
_STATUS_TIER = {"priority": "1", "keep": "2", "drop": "3"}

# 2026-07-21 (user): keep sheet cells scannable — trim the long-form cells. Full
# untrimmed detail stays in prospects.json (local state), only the sheet is capped.
_LONG_LIST_COLS = ("key_news", "buying_signals", "community_signals")
_LIST_MAX_ITEMS = 5  # was 3 — find_news already caps at MAX_NEWS = 5, and dropping
                     # two of five hid whole events rather than trimming prose
_ENTRY_MAX_CHARS = 180  # per entry, prose only (URLs/markers are budgeted separately)
# 2026-07-29 (user, reviewing the live Sheet: "fit_reason feels weak and vague"):
# fit_reason is a 5-line rubric dump and the old whole-string 400-char cap cut from
# the END — so Displacement, the LAST line and the one the outreach angle is built
# on, never reached the Sheet at all. Cleo's live cell stopped mid-word at
# "commercial product line ex…", showing the two weakest dimensions and hiding the
# two decisive ones. Budget per line instead: every dimension keeps its score.
_FIT_REASON_LINE_MAX_CHARS = 150

# A trailing recency marker written by gtm/enrich.py's signal-dating logic:
# "[stale]", "[undated]". Short and bracketed, so it can't collide with prose.
# Trailing sentence punctuation is tolerated after it: Claude routinely writes
# "... (source) [undated]." and an anchored-to-$ match silently fell through to
# the plain trimmer, deleting source, date and marker together (us-drone-20).
_RECENCY_MARKER_RE = re.compile(r"\s*(\[[^\[\]]{1,20}\])\s*[.;,]?\s*$")
_SOURCE_TAIL_RE = re.compile(r"\s\(([^()]{1,120})\)\s*[.;,]?\s*$")


def _trim(s: str, n: int) -> str:
    """Cap a string to n chars on a word boundary, adding an ellipsis when cut."""
    s = s.strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip() + "…"


def _trim_lines(s: str, n: int) -> str:
    """Trim each line to n chars, keeping every line. For cells whose value is a
    fixed set of labelled lines (fit_reason's rubric) where dropping a whole line
    loses a score, not just some prose."""
    return "\n".join(_trim(line, n) for line in s.strip().splitlines() if line.strip())


def _trim_keep_source(s: str, n: int) -> str:
    """Like _trim, but protects the two suffixes that carry the decision:
    the "(source, date)" parenthetical and a trailing "[stale]"/"[undated]" marker.
    Only the free text in front of them is trimmed.

    2026-07-24 fix: a cut source link is why community signals read as "no sources".
    2026-07-29 fix: the ")"-suffix test silently failed to fire on buying_signals,
    which end with the recency MARKER, not the parenthetical.
    2026-07-31 fix: both protections were last-character tests, so a trailing full
    stop ("... (breakingdefense.com, 2026-03).") defeated them and re-opened the
    exact same hole. Both are regexes now, and both tolerate trailing punctuation."""
    s = s.strip()
    marker = ""
    m = _RECENCY_MARKER_RE.search(s)
    if m:
        marker = " " + m.group(1)
        s = s[: m.start()].rstrip()
    source = ""
    m = _SOURCE_TAIL_RE.search(s)
    if m:
        source = f" ({m.group(1)})"
        s = s[: m.start()].rstrip()
    budget = max(n - len(source) - len(marker), 0)
    if len(s) > budget:
        s = s[:budget].rsplit(" ", 1)[0].rstrip() + "…"
    return s + source + marker


_URL_TAIL_RE = re.compile(r"\s\((https?://[^\s()]+)\)")
_DATE_STAMP_RE = re.compile(r"\s*(\[date:\s*\d{4}-\d{2}\])\s*$")


def _trim_news_entry(s: str, n: int) -> str:
    """Trim a key_news line's prose to n chars, charging neither the trailing URL
    nor the "[date: YYYY-MM]" stamp to the budget.

    2026-07-31: _trim_keep_source protected the URL parenthetical but counted it —
    breakingdefense's 103-char URL left 77 chars for the headline, so every news
    cell in the Sheet read as a fragment. The URL is not prose; a reader scans past
    it. Budget the words, preserve the link whole."""
    s = s.strip()
    stamp = ""
    m = _DATE_STAMP_RE.search(s)
    if m:
        stamp = " " + m.group(1)
        s = s[: m.start()].rstrip()
    url = ""
    m = _URL_TAIL_RE.search(s)
    if m:
        url = f" ({m.group(1)})"
        s = (s[: m.start()] + s[m.end():]).rstrip()
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip() + "…"
    return s + url + stamp


class Feedback(BaseModel):
    """One data/feedback.jsonl entry — the Learn stage's only input (CLAUDE.md).

    `origin` distinguishes feedback a user actually gave from Claude's own
    session/smoke-test write-ups: only "user" entries may drive a proposed
    company/ICP.md or company/denylist.md edit (see gtm/learn.py). The default,
    "session", covers every entry recorded before this field existed — checked
    2026-07-30: all 20 were live-smoke/dev-log notes, none a user's own words —
    and any future note Claude writes about its own run rather than repeating
    something the user said."""
    date: str
    run: str
    company: str
    feedback: str
    origin: str = "session"


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
    # 2026-07-28: the non-US half of "Procurement & compliance fit" (company/ICP.md).
    # Geography is not a scoring component (locked 2026-07-28): us_made_ndaa is one of
    # several procurement-evidence inputs to the Python-scored Budget & procurement
    # criterion (gtm/budget.py::score_budget, post-enrich); this field carries the
    # others (NATO stock number, national MoD framework, EASA/CAA type cert, BVLOS
    # waiver, awarded gov contract). "" = the hunt found no procurement evidence,
    # which contributes 0 to that criterion — never treat empty as "commercial,
    # therefore mid-band".
    compliance_evidence: str = ""
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
    # "yes"/"no" per contact, parallel to contact_name — did the SERP tie this person
    # to THIS company (gtm/contacts.py::Contact.verified)? Empty = the run was enriched
    # before the check existed; gtm/output.py treats that as "no data", not as "no".
    contact_verified: str = ""
    buying_signals: list[str] = []
    key_news: list[str] = []
    linkedin: str = ""
    headcount: str = ""  # employee-count band (e.g. "51-200"); "" when unknown — never a guessed number
    community_signals: list[str] = []
    # 2026-07-29: the noun phrase that fills {{trigger_event}} in an opener ("Air Force
    # Phase Three award"). Separate from buying_signals because those are verb-led clauses
    # with a source and a "why it matters" half — dropping one into the possessive slot
    # "Saw {{company_name}}'s ..." is what pushed "Saw Asylon's Awarded an Air Force Phase
    # Three contract to test DroneDog and ground robots networked into a single inspection
    # system" into the live sheet. Written by the signals stage (judgment), never derived
    # by truncating a signal (heuristics mangled half the stored corpus). "" = no usable
    # trigger, which leaves the token standing and blocks the row.
    trigger_phrase: str = ""
    outreach_angle: str = ""
    # stage "enrich" (displacement sub-step, gtm/displace.py) — state-only, feeds
    # draft's value-prop ammo; "" / [] when no named competitor was detected.
    competitor: str = ""
    competitor_weaknesses: list[str] = []
    # 2026-07-28: the OEM half of displacement (gtm/displace.py::detect_inhouse_case).
    # A short label ("drone-in-a-box enclosure", "OEM-built case") when the prospect
    # builds its own housing instead of buying one; mutually exclusive with
    # `competitor`, and the higher-value target of the two.
    inhouse_case: str = ""
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
    def fit_denominator(self) -> int:
        """100 once the Budget & procurement points are folded in, else 80.

        Two-phase fit (2026-07-31): pre-enrich, fit_score is only the 0-80 scrape-phase
        score, and rendering it as "/100" overstates a perfect scrape-phase score as
        80/100 rather than what it actually is. gtm/run.py::apply_budget_scores stamps
        a "Budget & procurement" line into fit_reason the moment it folds in the last
        20 points, so that marker (not a separate flag) is the signal the total is now
        the assembled 100-point score — same idempotency key apply_budget_scores itself
        uses to detect "already scored".

        One helper, two renderers. `why_fit` and `to_sheet_row` both write the score into
        the SAME sheet row, two columns apart; when each carried its own copy of this test
        they disagreed, and a drop row read "30/100" next to "Dropped (30/80)". Any future
        third renderer must call this rather than re-derive it."""
        return 100 if "Budget & procurement" in (self.fit_reason or "") else 80

    @property
    def why_fit(self) -> str:
        """One-line scannable summary for the Companies tab, so a reader gets the
        gist without opening the long fit_reason/buying_signals/key_news cells.
        Derived (not stored, like `tier`).

        2026-07-29 rewrite (user: "why_fit feels weak and vague"). It used to read
        band + case line + a verbatim copy of buying_signals[0] — the score column
        restated, then a duplicate of a cell two columns to the right. It never named
        the airframe we sized against, and never said why this company is displaceable,
        which is the actual answer to "why does this fit". Now:

            <band (score)> · <airframe + dims → our case line> · <displacement finding>

        The displacement segment falls back to the top buying signal only when there
        is no inhouse_case/competitor to report, so the duplication is the exception.

        Deliberately NOT included: "IP67 / MIL-STD-810H". Those are AeroVault's own
        specs, identical on every row, so they carry zero per-row information here —
        they stay in talking_points, where a rep needs the exact codes for the call
        (and stay banned from email bodies by gtm/draft.py::check_spec_jargon)."""
        band = {"1": "Strong fit", "2": "Possible fit", "3": "Dropped"}.get(self.tier, "Unscored")
        denom = self.fit_denominator
        head = f"{band} ({self.fit_score}/{denom})" if self.fit_score is not None else band
        parts = [head]

        # Prefer the dimension string: gtm/extract.py writes it as "<model>: <dims>",
        # so it already names the airframe and adds the measurement fit was scored on.
        airframe = self.drone_dimensions[0] if self.drone_dimensions else (
            self.drone_models[0] if self.drone_models else ""
        )
        airframe = _trim(airframe, 70)
        # No published dimensions means the case line was inferred from weight or from
        # nothing at all (Harris Aerial: Physical fit 8/30, yet best_case_line still
        # says AV-Convoy). Say so here, or a rep reads the arrow as a measured match
        # and names a line on the call that the airframe may not fit.
        unconfirmed = "" if self.drone_dimensions else " (size unconfirmed)"
        if airframe and self.best_case_line:
            parts.append(f"{airframe} → {self.best_case_line}{unconfirmed}")
        elif self.best_case_line:
            parts.append(f"{self.best_case_line} case{unconfirmed}")
        elif airframe:
            parts.append(airframe)

        if self.inhouse_case:
            # The label already carries the "OEM-" attribution; "builds own" repeats it.
            what = self.inhouse_case.replace("OEM-built ", "").replace("OEM-supplied ", "")
            parts.append(f"builds own {what}")
        elif self.competitor:
            parts.append(f"currently {self.competitor}")
        elif self.buying_signals:
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
                # 2026-07-29: an NDAA answer of None means "we checked and could not
                # tell" — a blank cell reads "nobody checked". Different states, and
                # the compliance column is one a reader acts on, so say which it is.
                row.append("unknown" if col == "us_made_ndaa" else "")
            elif col == "fit_score":
                # Same denominator why_fit uses, from the same helper — the two land two
                # columns apart in one row and must never disagree. Drop rows and fit-only
                # runs (start → fit → output, which never calls apply_budget_scores) are
                # both still on the 0-80 scrape-phase scale here.
                row.append(f"{v}/{self.fit_denominator}")
            elif isinstance(v, bool):
                row.append("yes" if v else "no")
            elif col == "fit_reason":
                row.append(_trim_lines(str(v), _FIT_REASON_LINE_MAX_CHARS))
            elif isinstance(v, list):
                if col in _LONG_LIST_COLS:
                    # long-form cells: top-N entries, each trimmed, one per line.
                    # key_news entries end in "(<url>)" — the URL isn't prose, so
                    # it's budgeted separately (_trim_news_entry) instead of eating
                    # into the same char cap as buying/community signals' sources.
                    trim = _trim_news_entry if col == "key_news" else _trim_keep_source
                    items = [trim(str(x), _ENTRY_MAX_CHARS) for x in v[:_LIST_MAX_ITEMS]]
                    row.append("\n".join(items))
                else:
                    row.append("; ".join(str(x) for x in v))  # short specs stay inline
            else:
                row.append(str(v))
        return row
