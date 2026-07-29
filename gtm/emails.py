"""S8 — email waterfall: pattern tier → provider-chain finder → AI hunt, all verified.

Stack cheap→expensive; a tier only runs when the previous one missed; every email is
validated before it reaches the sheet. The finder/verifier provider chain (Prospeo,
GetProspect, Hunter for finding; MyEmailVerifier, Abstract, GetProspect, Hunter for
verifying) lives in gtm/email_providers.py — read docs/tools/<vendor>.md before editing
any one vendor's calls. Live calls need that vendor's *_API_KEY set.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from gtm.contacts import serper_search
from gtm.email_providers import (
    AbstractProvider,
    GetProspectProvider,
    HunterProvider,
    MyEmailVerifierProvider,
    ProspeoProvider,
    finder_keys_configured,
)

MAX_PATTERNS = 3
MAX_DOMAINS = 3  # primary + at most 2 aliases; each extra domain costs verifications
ERROR_LOG = Path("data") / "errors.log"

# Credentials, licences and generational suffixes that ride along in a scraped
# LinkedIn name. Run test-batch-1: "Michael Lees, MSIS, PMP" split on whitespace
# took "PMP" as the surname and produced mpmp@easyaerial.com.
_NAME_SUFFIXES = frozenset(
    """pmp mba phd msis ms msc ma mha mpa jd md dds dvm pe pmi cfa cpa cissp cism cisa
    ccna ccnp rn np bsn emt ret usaf usmc usn jr sr ii iii iv v esq faa sphr shrm""".split()
)
# Particles that belong to a multi-word surname but never carry the mailbox name.
_NAME_PARTICLES = frozenset("van von der den de del della di da dos das la le du el bin al".split())

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


def parse_person_name(name: str) -> tuple[str, str]:
    """A scraped contact name → (first, last), with everything that isn't a name
    removed: parenthetical asides and pronouns, post-comma credential lists,
    trailing licences/generational suffixes, and non-latin decoration.

    Returns ("", "") when nothing name-shaped survives; the surname is "" for a
    single-token name (candidate_patterns already handles that shape)."""
    cleaned = re.sub(r"\([^)]*\)", " ", name or "")       # (she/her), (Ret.)
    cleaned = cleaned.split(",")[0]                        # ", MSIS, PMP"
    tokens = []
    for raw in cleaned.split():
        token = re.sub(r"[^A-Za-z'\-]", "", raw)           # strip emoji, dots, digits
        if not token:
            continue
        low = token.lower()
        if low in _NAME_SUFFIXES or low in _NAME_PARTICLES:
            continue
        tokens.append(token)
    if not tokens:
        return "", ""
    return tokens[0], tokens[-1] if len(tokens) > 1 else ""


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


def _log_error(error_log: Path, provider: str, context: str, err: Exception) -> None:
    error_log.parent.mkdir(parents=True, exist_ok=True)
    with error_log.open("a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} emails [{provider}/{context}] {err}\n")


def _call(provider, method: str, context: str, *args) -> dict | None:
    """One link of the chain. A vendor that raises (live timeouts and 5xx do happen —
    seen from GetProspect) must behave exactly like one that returned None: log it,
    defer, let the next provider answer. Without this, one flaky vendor mid-chain kills
    the whole waterfall and the contact silently gets no email at all."""
    try:
        return getattr(provider, method)(*args)
    except Exception as e:  # noqa: BLE001 — any vendor failure is just "can't answer"
        _log_error(ERROR_LOG, type(provider).__name__, context, e)
        return None


def _verify_chain(providers: list, email: str) -> dict:
    for p in providers:
        result = _call(p, "verify", "verify", email)
        if result is not None:
            return result
    return {}


def _find_chain(providers: list, first: str, last: str, domain: str) -> dict:
    # Provider adapters expect lowercase name parts (matches candidate_patterns'
    # _clean()); only the default provider-chain path normalizes case — a caller-
    # supplied finder= override still receives the raw first/last from waterfall().
    first, last = first.lower(), last.lower()
    for p in providers:
        result = _call(p, "find", "find", first, last, domain)
        if result is not None:
            return result
    return {}


_CATCH_ALL_CACHE: dict[str, bool] = {}


def is_catch_all(domain: str, verifier) -> bool:
    """Does this domain accept mail for local parts that don't exist? Probe once
    per domain (cached), with a random address nobody could own.

    Run test-batch-1 shipped three "verified" easyaerial.com addresses, one of
    them the garbage mpmp@ — the domain is accept-all, so a pattern-tier "valid"
    carried no information at all. A catch-all domain doesn't make an address
    wrong; it makes verification silent, and silence must not read as proof."""
    if not domain:
        return False
    if domain in _CATCH_ALL_CACHE:
        return _CATCH_ALL_CACHE[domain]
    probe = f"av-probe-{uuid4().hex[:10]}@{domain}"
    status = (verifier(probe) or {}).get("status", "")
    result = status in ("valid", "accept_all")
    _CATCH_ALL_CACHE[domain] = result
    return result


_MULTI_LABEL_TLDS = ("co.uk", "com.au", "co.nz", "co.jp", "com.br", "co.za", "com.mx")


def _registrable(host: str) -> str:
    """news.redcat.red → redcat.red (and foo.example.co.uk → example.co.uk)."""
    host = host.lower().strip().removeprefix("www.")
    labels = host.split(".")
    keep = 3 if host.endswith(_MULTI_LABEL_TLDS) else 2
    return ".".join(labels[-keep:]) if len(labels) > keep else host


def candidate_domains(website: str, company: str, key_news=()) -> list[str]:
    """The prospect's own domain first, then registrable aliases seen in the news
    links we already paid for — capped at MAX_DOMAINS.

    Run test-batch-1: Red Cat got 0 of 3 emails because the pattern tier only ever
    tried redcatholdings.com, while their press domain is redcat.red. Only domains
    the company name plausibly owns are kept — a publisher covering them is not an
    alias."""
    from gtm.discover import _name_matches_domain

    primary = _registrable(re.sub(r"^https?://", "", (website or "").strip()).split("/")[0])
    domains = [primary] if primary else []
    for line in key_news:
        for host in re.findall(r"https?://([A-Za-z0-9.\-]+)", line):
            alias = _registrable(host)
            if alias and alias not in domains and _name_matches_domain(company, alias):
                domains.append(alias)
    return domains[:MAX_DOMAINS]


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
    domains=None,
    providers=None,
    verifier=None,
    finder=None,
    search=serper_search,
) -> EmailResult:
    default_chain = providers is None and finder is None
    providers = providers if providers is not None else default_providers()
    verifier = verifier if verifier is not None else lambda email: _verify_chain(providers, email)
    finder = (
        finder if finder is not None else lambda f, l, d: _find_chain(providers, f, l, d)
    )
    first, last = parse_person_name(name)
    walk = [d for d in (domains or [domain]) if d]

    def pattern_tier(trusted: bool) -> EmailResult | None:
        for d in walk:
            for email in candidate_patterns(first, last, d):
                v = verifier(email)
                if v.get("status") == "valid":
                    return EmailResult(
                        email=email, tier="pattern",
                        status="verified" if trusted else "risky",
                        score=v.get("score"),
                    )
        return None

    def finder_tier() -> EmailResult | None:
        for d in walk:
            found = finder(first, last, d) or {}
            if found.get("email"):
                v = verifier(found["email"])
                return EmailResult(
                    email=found["email"], tier="hunter",
                    status=verdict(v.get("status", "unknown")), score=v.get("score"),
                )
        return None

    def ai_tier() -> EmailResult | None:
        for d in walk:
            email = _ai_hunt(name, d, search)
            if not email:
                continue
            v = verifier(email)
            status = verdict(v.get("status", "unknown"))
            if status != "reject":
                return EmailResult(email=email, tier="ai", status=status, score=v.get("score"))
        return None

    # On a catch-all domain the pattern tier can't prove anything (every guess
    # "verifies"), so the paid finder — which knows whether the mailbox actually
    # exists — goes first, and a pattern guess is only ever a `risky` fallback.
    catch_all = is_catch_all(walk[0], verifier) if walk else False
    tiers = (
        (finder_tier, ai_tier, lambda: pattern_tier(trusted=False))
        if catch_all
        else (lambda: pattern_tier(trusted=True), finder_tier, ai_tier)
    )
    for tier in tiers:
        result = tier()
        if result is not None:
            return result

    # A miss caused by missing config is not the same fact as a genuine miss —
    # run test-batch-1's cost log shows zero provider calls, i.e. Red Cat's 0/3
    # was never actually searched for.
    if default_chain and not finder_keys_configured():
        return EmailResult(status="no-finder-key")
    return EmailResult()
