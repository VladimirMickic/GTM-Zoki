"""EmailProvider protocol + adapters — Slice 2 provider chain (Task 2.1: Hunter).

`waterfall()` in gtm/emails.py will stack providers cheap→expensive (Task 2.4). Each
adapter answers `verify`/`find` for itself or returns None — meaning "can't answer,
not my capability, or quota hit — try the next provider." Read docs/tools/hunter.md
before touching HunterProvider's HTTP calls (endpoints, status semantics, error codes).
"""
from __future__ import annotations

import os
from typing import Protocol

import requests

HUNTER_FINDER_URL = "https://api.hunter.io/v2/email-finder"
HUNTER_VERIFIER_URL = "https://api.hunter.io/v2/email-verifier"

# 404 = no data, 429 = monthly quota exceeded, 451 = legal block for this person.
# All three are misses, not errors — the caller should try the next provider.
_MISS_STATUS_CODES = {404, 429, 451}


class EmailProvider(Protocol):
    name: str

    def verify(self, email: str) -> dict | None:
        """{"status": valid|invalid|accept_all|webmail|unknown|disposable, "score": int}
        or None if this provider can't answer (try the next provider)."""
        ...

    def find(self, first: str, last: str, domain: str) -> dict | None:
        """{"email": str, "score": int} or None if this provider can't answer."""
        ...


class HunterProvider:
    """Hunter.io email-finder + email-verifier (docs/tools/hunter.md)."""

    name = "hunter"

    def _get(self, url: str, params: dict) -> dict | None:
        api_key = os.environ.get("HUNTER_API_KEY")
        if not api_key:  # no key configured — can't answer, let the next provider try
            return None
        resp = requests.get(url, params=params, headers={"X-API-KEY": api_key}, timeout=20)
        if resp.status_code in _MISS_STATUS_CODES:
            return None
        resp.raise_for_status()
        return resp.json().get("data", {})

    def verify(self, email: str) -> dict | None:
        data = self._get(HUNTER_VERIFIER_URL, {"email": email})
        if data is None:
            return None
        return {"status": data.get("status"), "score": data.get("score")}

    def find(self, first: str, last: str, domain: str) -> dict | None:
        data = self._get(
            HUNTER_FINDER_URL, {"domain": domain, "first_name": first, "last_name": last}
        )
        if not data or not data.get("email"):
            return None
        return {"email": data["email"], "score": data.get("score")}


MYEMAILVERIFIER_URL = "https://api.myemailverifier.com/api/validate_single.php"

# Vendor status (capitalized) -> hunter-style verdict vocabulary (docs/tools/myemailverifier.md).
_MEV_STATUS_MAP = {
    "Valid": "valid",
    "Invalid": "invalid",
    "Catch-All": "accept_all",
    "Unknown": "unknown",
    "Greylisted": "unknown",  # server deferred, re-check later
    "Disposable": "invalid",
    "Role-Based": "invalid",
    "Spam Trap": "invalid",
}


class MyEmailVerifierProvider:
    """MyEmailVerifier single-email verification (docs/tools/myemailverifier.md). Verify-only."""

    name = "myemailverifier"

    def verify(self, email: str) -> dict | None:
        api_key = os.environ.get("MYEMAILVERIFIER_API_KEY")
        if not api_key:  # no key configured — can't answer, let the next provider try
            return None
        resp = requests.get(
            MYEMAILVERIFIER_URL, params={"apikey": api_key, "email": email}, timeout=20
        )
        # Docs surface no explicit 429 body — treat any non-200 as "stop this tier",
        # never raise. Covers quota exhaustion and generic HTTP errors alike.
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Non-zero error_code is also a miss per the doc's Errors section.
        if str(data.get("error_code", 0)) not in ("0", "0.0"):
            return None
        status = data.get("Status")
        verdict = _MEV_STATUS_MAP.get(status)
        if verdict is None:
            return None
        if verdict == "valid" and str(data.get("catch_all", "")).lower() == "true":
            verdict = "accept_all"
        score = 100 if status == "Valid" else 0
        return {"status": verdict, "score": score}

    def find(self, first: str, last: str, domain: str) -> dict | None:
        # MyEmailVerifier has no email-finder capability — verify-only vendor.
        return None


ABSTRACT_URL = "https://emailvalidation.abstractapi.com/v1/"


class AbstractProvider:
    """Abstract Email Validation API (docs/tools/abstract.md). Verify-only."""

    name = "abstract"

    def verify(self, email: str) -> dict | None:
        api_key = os.environ.get("ABSTRACT_API_KEY")
        if not api_key:  # no key configured — can't answer, let the next provider try
            return None
        resp = requests.get(
            ABSTRACT_URL, params={"api_key": api_key, "email": email}, timeout=20
        )
        # 429 = req/s rate limit, 422 = monthly quota exhausted (per the doc's Errors
        # section) — treat both, and any other HTTP error, as a miss. Never raise.
        if resp.status_code != 200:
            return None
        data = resp.json()
        deliverability = data.get("deliverability")
        catch_all = (data.get("is_catchall_email") or {}).get("value")
        if deliverability == "DELIVERABLE":
            verdict = "accept_all" if catch_all else "valid"
        elif deliverability == "UNDELIVERABLE":
            verdict = "invalid"
        else:
            verdict = "unknown"
        quality_score = data.get("quality_score")
        score = round(float(quality_score) * 100) if quality_score is not None else 0
        return {"status": verdict, "score": score}

    def find(self, first: str, last: str, domain: str) -> dict | None:
        # Abstract Email Validation has no email-finder capability — verify-only vendor.
        return None


GETPROSPECT_FIND_URL = "https://api.getprospect.com/public/v1/email/find"
GETPROSPECT_VERIFY_URL = "https://api.getprospect.com/public/v1/email/verify"

# GetProspect's response-body field names are unconfirmed (docs/tools/getprospect.md —
# the "Try It" example payloads are behind readme.io's JS panel, unreachable). These are
# best-guess field paths; a wrong guess just makes this provider always miss (falls
# through to Hunter), never crashes. Fix once a live call confirms the real shape.
_GETPROSPECT_EMAIL_PATHS = [("email",), ("data", "email")]
_GETPROSPECT_STATUS_PATHS = [("status",), ("data", "status")]

# Same vocabulary as MyEmailVerifier's map — best guess at GetProspect's status strings.
_GETPROSPECT_STATUS_MAP = {
    "valid": "valid",
    "invalid": "invalid",
    "catch-all": "accept_all",
    "catch_all": "accept_all",
    "unknown": "unknown",
    "disposable": "invalid",
}


def _dig(data: dict, path: tuple[str, ...]):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


class GetProspectProvider:
    """GetProspect email finder + verifier (docs/tools/getprospect.md). Response field
    names are unconfirmed — see the docs file before trusting this over other providers."""

    name = "getprospect"

    def _get(self, url: str, params: dict) -> dict | None:
        api_key = os.environ.get("GETPROSPECT_API_KEY")
        if not api_key:  # no key configured — can't answer, let the next provider try
            return None
        resp = requests.get(url, params=params, headers={"apiKey": api_key}, timeout=20)
        if resp.status_code != 200:
            return None
        return resp.json()

    def verify(self, email: str) -> dict | None:
        data = self._get(GETPROSPECT_VERIFY_URL, {"email": email})
        if data is None:
            return None
        raw_status = next(
            (v for p in _GETPROSPECT_STATUS_PATHS if (v := _dig(data, p)) is not None), None
        )
        if not isinstance(raw_status, str):
            return None
        verdict = _GETPROSPECT_STATUS_MAP.get(raw_status.lower())
        if verdict is None:
            return None
        return {"status": verdict, "score": 100 if verdict == "valid" else 0}

    def find(self, first: str, last: str, domain: str) -> dict | None:
        data = self._get(
            GETPROSPECT_FIND_URL, {"name": f"{first} {last}".strip(), "company": domain}
        )
        if data is None:
            return None
        email = next(
            (v for p in _GETPROSPECT_EMAIL_PATHS if (v := _dig(data, p)) is not None), None
        )
        if not isinstance(email, str) or not email:
            return None
        return {"email": email, "score": 0}


PROSPEO_ENRICH_URL = "https://api.prospeo.io/enrich-person"

# HTTP 400/429 both carry a JSON {"error": true, "error_code": ...} body per the doc's
# Errors section (NO_MATCH, INVALID_DATAPOINTS, INSUFFICIENT_CREDITS, INVALID_API_KEY,
# INVALID_REQUEST, INTERNAL_ERROR, and 429 = rate limit) — all are misses, never raise.
_PROSPEO_MISS_STATUS_CODES = {400, 429}


class ProspeoProvider:
    """Prospeo /enrich-person (docs/tools/prospeo.md). Find-only — no verify endpoint used."""

    name = "prospeo"

    def verify(self, email: str) -> dict | None:
        # Prospeo is a finder, not a verifier — no /email-verifier-style endpoint is
        # used here. Always defer to the next provider in the waterfall.
        return None

    def find(self, first: str, last: str, domain: str) -> dict | None:
        api_key = os.environ.get("PROSPEO_API_KEY")
        if not api_key:  # no key configured — can't answer, let the next provider try
            return None
        resp = requests.post(
            PROSPEO_ENRICH_URL,
            json={
                "only_verified_email": True,
                "data": {
                    "first_name": first,
                    "last_name": last,
                    "company_website": domain,
                },
            },
            headers={"X-KEY": api_key, "Content-Type": "application/json"},
            timeout=20,
        )
        if resp.status_code in _PROSPEO_MISS_STATUS_CODES:
            return None
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            return None
        email = ((data.get("person") or {}).get("email") or {})
        address = email.get("email")
        if not address:  # null/absent = miss, fall through the waterfall
            return None
        score = 100 if email.get("status") == "VERIFIED" else 0
        return {"email": address, "score": score}
