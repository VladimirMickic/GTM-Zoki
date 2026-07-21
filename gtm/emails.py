"""S8 — email waterfall: pattern tier → provider-chain finder → AI hunt, all verified.

Stack cheap→expensive; a tier only runs when the previous one missed; every email is
validated before it reaches the sheet. The finder/verifier provider chain (Prospeo,
GetProspect, Hunter for finding; MyEmailVerifier, Abstract, GetProspect, Hunter for
verifying) lives in gtm/email_providers.py — read docs/tools/<vendor>.md before editing
any one vendor's calls. Live calls need that vendor's *_API_KEY set.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from gtm.contacts import serper_search
from gtm.email_providers import (
    AbstractProvider,
    GetProspectProvider,
    HunterProvider,
    MyEmailVerifierProvider,
    ProspeoProvider,
)

MAX_PATTERNS = 3

_hunter = HunterProvider()

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


def hunter_verify(email: str) -> dict:
    """Thin delegate to HunterProvider (gtm/email_providers.py) — kept so waterfall()'s
    default verifier and any existing callers see the pre-Slice-2 shape (dict, never None)."""
    return _hunter.verify(email) or {}


def hunter_find(first: str, last: str, domain: str) -> dict:
    """Thin delegate to HunterProvider — see hunter_verify docstring."""
    return _hunter.find(first, last, domain) or {}


def default_providers() -> list:
    """Ordered provider chain (Task 2.4). Each adapter answers verify/find for itself
    or returns None ("can't answer / not my capability / quota hit") so the chain
    naturally skips it: a verify walk yields MEV -> Abstract -> GetProspect -> Hunter
    (Prospeo is find-only and always defers); a find walk yields Prospeo -> GetProspect
    -> Hunter (MEV/Abstract are verify-only and always defer). GetProspect sits before
    Hunter (free tier ahead of the more expensive/paid one). One ordered list handles
    both directions."""
    return [
        MyEmailVerifierProvider(),
        AbstractProvider(),
        ProspeoProvider(),
        GetProspectProvider(),
        HunterProvider(),
    ]


def _verify_chain(providers: list, email: str) -> dict:
    for p in providers:
        result = p.verify(email)
        if result is not None:
            return result
    return {}


def _find_chain(providers: list, first: str, last: str, domain: str) -> dict:
    # Provider adapters expect lowercase name parts (matches candidate_patterns'
    # _clean()); only the default provider-chain path normalizes case — a caller-
    # supplied finder= override still receives the raw first/last from waterfall().
    first, last = first.lower(), last.lower()
    for p in providers:
        result = p.find(first, last, domain)
        if result is not None:
            return result
    return {}


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
    providers=None,
    verifier=None,
    finder=None,
    search=serper_search,
) -> EmailResult:
    providers = providers if providers is not None else default_providers()
    verifier = verifier if verifier is not None else lambda email: _verify_chain(providers, email)
    finder = (
        finder if finder is not None else lambda f, l, d: _find_chain(providers, f, l, d)
    )
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
