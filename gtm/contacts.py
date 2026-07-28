"""S4 — contact discovery via Serper `site:linkedin.com/in` (names/titles/LinkedIn only).

No emails in the demo (decision locked). Parser + ranking are deterministic and
fixture-tested; the Serper call is the only network piece.
"""
from __future__ import annotations

import os
import re

import requests
from pydantic import BaseModel

SERPER_URL = "https://google.serper.dev/search"

# " - " or " – " separated: Name - Title - Company | LinkedIn
_SEP = re.compile(r"\s+[-–—]\s+")

# who actually buys transport cases: ops/procurement/founders first (ICP.md "Target titles")
_RANK_KEYWORDS = [
    ("founder", 100), ("chief", 90), ("vp", 85), ("vice president", 85),
    ("head of", 80), ("director", 75), ("procurement", 72), ("supply chain", 72),
    ("purchasing", 72), ("sourcing", 72), ("operations", 70), ("product", 65),
    ("program", 60), ("logistics", 60), ("sales", 50), ("manager", 40),
]

# buyer-title terms the query biases toward, so the SERP surfaces procurement/ops
# people instead of a defense prime's public-facing engineers (us-drone-3 bug).
_BUYER_TERMS = (
    "procurement", "supply chain", "purchasing", "operations",
    "program", "logistics", "product", "founder", "director", "head of",
)

# never a target for outreach — excluded from find_contacts entirely, never a fallback.
# These kill non-buyers the SERP drags in (engineers, students, academics) —
# us-drone-3 shipped a "Chief Engineer" and a Penn State student.
_EXCLUDE_KEYWORDS = (
    "engineer", "student", "intern", "university",
    "professor", "researcher", "scientist",
)

# CEO is excluded per ICP.md, but conditionally: at a founder-led company the founder
# IS the CEO, and ICP.md ranks Founder #1. cold-0727 (Arcsky) hit the collision head
# on — both co-founders titled "Co-CEO | Co-Founder", both ranked 100, both dropped,
# company left with zero contacts. So CEO only disqualifies when no founder term is
# present. Both spellings are listed because "ceo" is word-boundary matched and
# "Chief Executive Officer" slipped through the old tuple entirely.
_CEO_TITLES = ("ceo", "chief executive")
_FOUNDER_TITLES = ("founder", "co-founder", "founding partner")


class Contact(BaseModel):
    name: str
    title: str = ""
    linkedin: str = ""


# Ambient per-run CostLog for serper credit tracking. CLI stages set this once
# (gtm/run.py) so every serper_search call logs 1 credit into the run's cost
# file without threading a costlog through every stage signature. None = no
# logging (the default; unit tests inject fake `search=` and never reach here).
_active_costlog = None


def set_active_costlog(costlog) -> None:
    global _active_costlog
    _active_costlog = costlog


def serper_search(query: str, num: int = 10, *, costlog=None) -> list[dict]:
    resp = requests.post(
        SERPER_URL,
        headers={"X-API-KEY": os.environ["SERPER_API_KEY"], "Content-Type": "application/json"},
        json={"q": query, "num": num, "gl": "us", "hl": "en"},
        timeout=10,
    )
    resp.raise_for_status()
    cl = costlog if costlog is not None else _active_costlog
    if cl is not None:
        cl.record_serper(credits=1)  # 1 credit per search (Serper free tier)
    return resp.json().get("organic", [])


def build_contact_query(company: str) -> str:
    # "drone" disambiguates generic names ("Paladin" alone matches surnames); the
    # OR-group biases the SERP toward buyer titles, not engineers. Requires one
    # buyer term present — find_contacts widens to build_broad_query if this is dry.
    buyers = " OR ".join(f'"{t}"' if " " in t else t for t in _BUYER_TERMS)
    return f'site:linkedin.com/in "{company}" drone ({buyers})'


def build_broad_query(company: str) -> str:
    # fallback when the buyer-biased query surfaces nobody (secretive primes have
    # few public procurement profiles) — no buyer terms, excludes still applied.
    return f'site:linkedin.com/in "{company}" drone'


def _strip_trailing_employer(job: str, company: str) -> str:
    """Drop a trailing "at/@ <our company>" — the SERP's own suffix, not part of the title.

    Matched as a PREFIX of the company name, because Serper truncates: "@ Neros ..." is
    all that survives of "@ Neros Technologies", and an exact match never fires. A
    trailing "at <someone else>" is real information (they work elsewhere) and is kept,
    so the prefix must be a whole leading word of the company, not any substring.
    """
    m = re.search(r"\s*(?:at|@)\s+(.+)$", job, flags=re.I)
    if m is None:
        return job
    tail = m.group(1).strip().rstrip(",")
    words = company.split()
    prefixes = {" ".join(words[:i]).lower() for i in range(1, len(words) + 1)}
    return job[: m.start()].rstrip() if tail.lower() in prefixes else job


def parse_linkedin_result(title: str, link: str, company: str = "") -> Contact | None:
    if "/in/" not in link:
        return None  # company page or other non-profile result
    title = title.replace("| LinkedIn", "").replace("- LinkedIn", "").strip()
    parts = _SEP.split(title)
    if len(parts) < 2:
        return None
    job = parts[1].strip()
    # Serper truncates long SERP titles with a trailing ellipsis ("... " or "…"), which
    # broke the $-anchored company strip below — us-drone-6 shipped
    # "Head of Mission Success @ Neros ..." straight into the sheet. Strip it first.
    job = re.sub(r"\s*(?:\.{3}|…)\s*$", "", job)
    if company:
        job = _strip_trailing_employer(job, company)
    return Contact(name=parts[0].strip(), title=job, linkedin=link)


def _rank(c: Contact) -> int:
    t = c.title.lower()
    return max(
        (score for kw, score in _RANK_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", t)),
        default=0,
    )


def top_contact_fields(contacts: list[Contact], n: int = 3) -> tuple[str, str, str]:
    """Join the top-n ranked contacts into the three sheet cells, parallel order."""
    top = contacts[:n]
    return (
        "; ".join(c.name for c in top),
        "; ".join(c.title for c in top),
        "; ".join(c.linkedin for c in top),
    )


def _collect(query: str, company: str, search) -> list[Contact]:
    """Parse one SERP into ranked buyer contacts: drop non-profiles, excluded
    titles (ceo/engineer/student/...), and rank-0 unrecognized titles."""
    out = []
    for r in search(query, num=10):
        c = parse_linkedin_result(r.get("title", ""), r.get("link", ""), company)
        if c is not None and not _is_excluded(c) and _rank(c) > 0:
            out.append(c)
    return out


def find_contacts(company: str, *, search=serper_search) -> list[Contact]:
    contacts = _collect(build_contact_query(company), company, search)
    if not contacts:  # buyer-biased query dry — widen to the broad query, same filters
        contacts = _collect(build_broad_query(company), company, search)
    return sorted(contacts, key=_rank, reverse=True)


def _is_excluded(c: Contact) -> bool:
    t = c.title.lower()
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _EXCLUDE_KEYWORDS):
        return True
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _CEO_TITLES):
        # a founder who is also CEO stays — see _CEO_TITLES. The founder carve-out is
        # scoped to this collision only: it never rescues a title excluded above, so a
        # "Founding Engineer" is still dropped as an engineer.
        return not any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _FOUNDER_TITLES)
    return False
