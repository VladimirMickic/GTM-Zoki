"""HubSpot CRM sink — company + contact upsert with domain-based dedupe (Slice 7,
Task 7.1). Built from the live doc research in docs/tools/hubspot.md — read that
first for endpoint shapes/gotchas.

Companies have no built-in unique property, so they're upserted via search-by-
domain then create-or-update-by-id (not the literal `batch/upsert` endpoint).
Contacts CAN use `email` as `idProperty` directly via `batch/upsert`. Associations
require both a real company ID and real contact IDs, so the call order per
prospect is always: search/create-or-update company -> batch/upsert contacts ->
associate.

Cross-cutting "log & skip" convention, matching gtm/github_state.py: the auth key
is read from `os.environ["HUBSPOT_SERVICE_KEY"]` at call time (never import time);
every failure (missing key, network error, non-2xx) is caught, written to
error_log, and that prospect (or just that contact/association) is skipped rather
than raising. A HubSpot push failure must never take down the pipeline.
"""
from __future__ import annotations

import time
from os import environ
from pathlib import Path

import requests

from gtm.schema import Prospect

API_BASE = "https://api.hubapi.com"
ERROR_LOG = Path("data") / "errors.log"

_TIMEOUT = 20


def _log_error(error_log: Path, context: str, err: Exception | str) -> None:
    error_log.parent.mkdir(parents=True, exist_ok=True)
    with error_log.open("a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} hubspot [{context}] {err}\n")


def _headers() -> dict[str, str] | None:
    """None means "no Service Key configured" — caller no-ops, never raises."""
    key = environ.get("HUBSPOT_SERVICE_KEY")
    if not key:
        return None
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _bare_domain(website: str) -> str:
    """Strip scheme + path — HubSpot's `domain` property expects a bare domain
    (e.g. "tealdrones.com", not "https://tealdrones.com/products")."""
    domain = website.strip()
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    return domain.split("/", 1)[0]


def _parse_email(entry: str) -> str | None:
    """Parses one "email (status)" entry from Prospect.contact_emails. Returns
    None for a miss ("-", per the schema.py comment) or an empty entry."""
    entry = entry.strip()
    if not entry or entry == "-":
        return None
    email = entry.split(" (", 1)[0].strip()
    if not email or email == "-":
        return None
    return email


def _split_contacts(prospect: Prospect) -> list[dict]:
    """Reconstructs one contact per index from the "; "-joined parallel strings
    (contact_name/contact_title/contact_linkedin/contact_emails). Skips any index
    whose email entry is a miss — never push a contact to HubSpot with no real
    email."""
    names = prospect.contact_name.split("; ") if prospect.contact_name else []
    titles = prospect.contact_title.split("; ") if prospect.contact_title else []
    linkedins = prospect.contact_linkedin.split("; ") if prospect.contact_linkedin else []
    emails = prospect.contact_emails.split("; ") if prospect.contact_emails else []

    contacts = []
    for i, name in enumerate(names):
        email_entry = emails[i] if i < len(emails) else "-"
        email = _parse_email(email_entry)
        if not email:
            continue
        first, _, last = name.strip().partition(" ")
        contacts.append(
            {
                "email": email,
                "firstname": first,
                "lastname": last,
                "jobtitle": titles[i] if i < len(titles) else "",
                "linkedin": linkedins[i] if i < len(linkedins) else "",
            }
        )
    return contacts


def _upsert_company(
    headers: dict[str, str], domain: str, name: str, error_log: Path
) -> str | None:
    """Search-by-domain, then PATCH (found) or POST (not found) — the idempotent
    dedupe path documented in docs/tools/hubspot.md section 1, since companies
    have no built-in unique property to key a literal batch/upsert off. Returns
    the HubSpot company record ID, or None on any failure (logged)."""
    search_url = f"{API_BASE}/crm/v3/objects/companies/search"
    search_body = {
        "filterGroups": [
            {"filters": [{"propertyName": "domain", "operator": "EQ", "value": domain}]}
        ]
    }
    try:
        resp = requests.post(search_url, headers=headers, json=search_body, timeout=_TIMEOUT)
    except requests.RequestException as e:
        _log_error(error_log, "upsert_company:search", e)
        return None
    if resp.status_code != 200:
        _log_error(
            error_log, "upsert_company:search", f"HTTP {resp.status_code}: {resp.text[:200]}"
        )
        return None
    try:
        results = resp.json().get("results", [])
    except ValueError as e:
        _log_error(error_log, "upsert_company:search", e)
        return None

    properties = {"name": name, "domain": domain}

    if results:
        company_id = results[0]["id"]
        url = f"{API_BASE}/crm/v3/objects/companies/{company_id}"
        try:
            resp = requests.patch(
                url, headers=headers, json={"properties": properties}, timeout=_TIMEOUT
            )
        except requests.RequestException as e:
            _log_error(error_log, "upsert_company:update", e)
            return None
        if resp.status_code != 200:
            _log_error(
                error_log,
                "upsert_company:update",
                f"HTTP {resp.status_code}: {resp.text[:200]}",
            )
            return None
        return company_id

    url = f"{API_BASE}/crm/v3/objects/companies"
    try:
        resp = requests.post(
            url, headers=headers, json={"properties": properties}, timeout=_TIMEOUT
        )
    except requests.RequestException as e:
        _log_error(error_log, "upsert_company:create", e)
        return None
    if resp.status_code != 201:
        _log_error(
            error_log, "upsert_company:create", f"HTTP {resp.status_code}: {resp.text[:200]}"
        )
        return None
    try:
        return resp.json()["id"]
    except (ValueError, KeyError) as e:
        _log_error(error_log, "upsert_company:create", e)
        return None


def _upsert_contacts(
    headers: dict[str, str], contacts: list[dict], error_log: Path
) -> list[str]:
    """Batch-upserts contacts keyed by `email` (a valid built-in idProperty for
    contacts, unlike companies). Returns the HubSpot contact record IDs from the
    response, or [] on any failure (logged) or if there were no contacts."""
    if not contacts:
        return []
    url = f"{API_BASE}/crm/v3/objects/contacts/batch/upsert"
    inputs = [
        {
            "id": c["email"],
            "idProperty": "email",
            "properties": {
                "email": c["email"],
                "firstname": c["firstname"],
                "lastname": c["lastname"],
                "jobtitle": c["jobtitle"],
                "hs_linkedin_url": c["linkedin"],
            },
        }
        for c in contacts
    ]
    try:
        resp = requests.post(url, headers=headers, json={"inputs": inputs}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        _log_error(error_log, "upsert_contacts", e)
        return []
    if resp.status_code != 200:
        _log_error(
            error_log, "upsert_contacts", f"HTTP {resp.status_code}: {resp.text[:200]}"
        )
        return []
    try:
        results = resp.json().get("results", [])
    except ValueError as e:
        _log_error(error_log, "upsert_contacts", e)
        return []
    return [r["id"] for r in results if "id" in r]


def _associate_contacts(
    headers: dict[str, str], contact_ids: list[str], company_id: str, error_log: Path
) -> None:
    """Associates each contact with its company as the contact's primary company
    (associationTypeId 1). Requires real HubSpot record IDs for both sides — only
    called after both the company and contact upserts have succeeded. Best-effort:
    logs and returns on failure, never raises."""
    if not contact_ids:
        return
    url = f"{API_BASE}/crm/v4/associations/contact/company/batch/create"
    inputs = [
        {
            "from": {"id": cid},
            "to": {"id": company_id},
            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 1}],
        }
        for cid in contact_ids
    ]
    try:
        resp = requests.post(url, headers=headers, json={"inputs": inputs}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        _log_error(error_log, "associate_contacts", e)
        return
    if resp.status_code not in (200, 201):
        _log_error(
            error_log, "associate_contacts", f"HTTP {resp.status_code}: {resp.text[:200]}"
        )


def push_to_hubspot(prospects: list[Prospect], *, error_log: Path = ERROR_LOG) -> int:
    """Maps each Prospect to a HubSpot company + contact(s) and upserts them:
    company via search-by-domain -> create-or-update-by-id (idempotent dedupe,
    since companies have no built-in unique property); contacts via batch/upsert
    keyed on email; then associates each contact to the company as its primary
    company. Call order per prospect: company, then contacts, then associate.

    Does NOT filter by `status` — the caller decides which prospects to pass
    (mirrors gtm/output.py's push_to_sheet receiving an already-relevant list).

    Missing `HUBSPOT_SERVICE_KEY` makes the whole call a no-op returning 0. Any
    HTTP failure for one prospect is logged to error_log and that prospect is
    skipped — this function never raises.

    Returns the count of prospects successfully pushed (company create/update
    succeeded; contact sync + association are best-effort on top of that).
    """
    headers = _headers()
    if headers is None:
        _log_error(error_log, "push_to_hubspot", "HUBSPOT_SERVICE_KEY not set")
        return 0

    count = 0
    for prospect in prospects:
        domain = _bare_domain(prospect.website)
        company_id = _upsert_company(headers, domain, prospect.company, error_log)
        if company_id is None:
            continue

        contacts = _split_contacts(prospect)
        contact_ids = _upsert_contacts(headers, contacts, error_log)
        _associate_contacts(headers, contact_ids, company_id, error_log)

        count += 1
    return count
