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
