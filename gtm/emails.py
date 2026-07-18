"""S8 — email waterfall: pattern tier → Hunter.io finder → AI hunt, all verified.

Stack cheap→expensive; a tier only runs when the previous one missed; every email is
validated before it reaches the sheet (docs/tools/hunter.md — read it before editing
the Hunter calls). Live calls need HUNTER_API_KEY.
"""
from __future__ import annotations

import os
import re

import requests
from pydantic import BaseModel

from gtm.contacts import serper_search

HUNTER_FINDER_URL = "https://api.hunter.io/v2/email-finder"
HUNTER_VERIFIER_URL = "https://api.hunter.io/v2/email-verifier"
MAX_PATTERNS = 3

# hunter verifier status → our sheet label (docs/tools/hunter.md acceptance rule)
_VERDICTS = {
    "valid": "verified",
    "accept_all": "risky",
    "webmail": "risky",
    "unknown": "unverified",
    "invalid": "reject",
    "disposable": "reject",
}


class EmailResult(BaseModel):
    email: str = ""
    tier: str = ""    # pattern | hunter | ai | "" (not found)
    status: str = ""  # verified | risky | unverified | "" (not found)
    score: int | None = None


def verdict(status: str) -> str:
    return _VERDICTS.get(status, "unverified")


def _clean(token: str) -> str:
    return re.sub(r"[^a-z]", "", token.lower())


def candidate_patterns(first: str, last: str, domain: str) -> list[str]:
    first, last = _clean(first), _clean(last)
    if not first:
        return []
    if not last:
        return [f"{first}@{domain}"]
    return [
        f"{first}.{last}@{domain}",
        f"{first}@{domain}",
        f"{first[0]}{last}@{domain}",
    ][:MAX_PATTERNS]


def split_contact_names(joined: str) -> list[str]:
    return [n.strip() for n in joined.split(";") if n.strip()]


def _hunter_get(url: str, params: dict) -> dict:
    resp = requests.get(
        url, params=params, headers={"X-API-KEY": os.environ["HUNTER_API_KEY"]}, timeout=20
    )
    if resp.status_code in (404, 451):  # no data / legal block: a miss, not an error
        return {}
    resp.raise_for_status()
    return resp.json().get("data", {})


def hunter_verify(email: str) -> dict:
    return _hunter_get(HUNTER_VERIFIER_URL, {"email": email})


def hunter_find(first: str, last: str, domain: str) -> dict:
    return _hunter_get(
        HUNTER_FINDER_URL, {"domain": domain, "first_name": first, "last_name": last}
    )


def _ai_hunt(name: str, domain: str, search) -> str:
    """Tier 3: scan public serp snippets for an address at the prospect's domain."""
    results = search(f'"{name}" "{domain}" email OR contact', num=10)
    pattern = re.compile(rf"[a-z0-9._%+-]+@{re.escape(domain)}", re.I)
    for r in results:
        m = pattern.search(f"{r.get('title', '')} {r.get('snippet', '')}")
        if m:
            return m.group(0).lower()
    return ""


def waterfall(
    name: str,
    domain: str,
    *,
    verifier=hunter_verify,
    finder=hunter_find,
    search=serper_search,
) -> EmailResult:
    parts = name.split()
    first, last = parts[0], parts[-1] if len(parts) > 1 else ""

    for email in candidate_patterns(first, last, domain):  # tier 1 — free patterns
        v = verifier(email)
        if v.get("status") == "valid":
            return EmailResult(email=email, tier="pattern", status="verified", score=v.get("score"))

    found = finder(first, last, domain) or {}  # tier 2 — hunter finder
    if found.get("email"):
        v = verifier(found["email"])
        return EmailResult(
            email=found["email"], tier="hunter", status=verdict(v.get("status", "unknown")),
            score=v.get("score"),
        )

    email = _ai_hunt(name, domain, search)  # tier 3 — public-web scan
    if email:
        v = verifier(email)
        status = verdict(v.get("status", "unknown"))
        if status != "reject":
            return EmailResult(email=email, tier="ai", status=status, score=v.get("score"))
    return EmailResult()
