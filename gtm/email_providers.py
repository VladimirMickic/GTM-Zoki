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
