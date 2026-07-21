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

# who actually buys transport cases: ops/product/founders first
_RANK_KEYWORDS = [
    ("founder", 100), ("ceo", 95), ("chief", 90), ("vp", 85), ("vice president", 85),
    ("head of", 80), ("director", 75), ("operations", 70), ("product", 65),
    ("program", 60), ("logistics", 60), ("sales", 50), ("manager", 40),
]


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
    # bare "drone" disambiguates generic names ("Paladin" alone matches surnames)
    return f'site:linkedin.com/in "{company}" drone'


def parse_linkedin_result(title: str, link: str, company: str = "") -> Contact | None:
    if "/in/" not in link:
        return None  # company page or other non-profile result
    title = title.replace("| LinkedIn", "").replace("- LinkedIn", "").strip()
    parts = _SEP.split(title)
    if len(parts) < 2:
        return None
    job = parts[1].strip()
    if company:
        job = re.sub(rf"\s*(?:at|@)\s+{re.escape(company)}\s*$", "", job, flags=re.I)
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


def find_contacts(company: str, *, search=serper_search) -> list[Contact]:
    results = search(build_contact_query(company), num=10)
    contacts = []
    for r in results:
        c = parse_linkedin_result(r.get("title", ""), r.get("link", ""), company)
        if c is not None:
            contacts.append(c)
    return sorted(contacts, key=_rank, reverse=True)
