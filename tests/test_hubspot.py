"""Task 7.1: gtm/hubspot.py — field mapping + upsert, mocked requests only.

No real network calls, no real HUBSPOT_SERVICE_KEY needed. Mirrors
tests/test_github_state.py's monkeypatch-the-requests-call style.
"""
from pathlib import Path

import requests

import gtm.hubspot as hs
from gtm.schema import Prospect


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


def _prospect(**overrides):
    base = dict(
        company="Teal Drones",
        website="https://tealdrones.com/products",
        contact_name="Jane Doe",
        contact_title="VP Engineering",
        contact_linkedin="https://linkedin.com/in/janedoe",
        contact_emails="jane@tealdrones.com (verified)",
        status="priority",
    )
    base.update(overrides)
    return Prospect(**base)


# ---------- missing token ----------


def test_push_to_hubspot_missing_token_no_op_returns_0(monkeypatch, tmp_path):
    monkeypatch.delenv("HUBSPOT_SERVICE_KEY", raising=False)

    def fail(*a, **k):
        raise AssertionError("should not call requests without a token")

    monkeypatch.setattr(hs.requests, "post", fail)
    monkeypatch.setattr(hs.requests, "patch", fail)
    error_log = tmp_path / "errors.log"

    count = hs.push_to_hubspot([_prospect()], error_log=error_log)

    assert count == 0
    assert error_log.exists()


# ---------- normal push: new company, one contact ----------


def test_push_to_hubspot_normal_push_creates_company_and_contact(monkeypatch, tmp_path):
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "svc-key")
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json, timeout))
        if url.endswith("/crm/v3/objects/companies/search"):
            return FakeResponse(200, {"results": []})
        if url.endswith("/crm/v3/objects/companies"):
            return FakeResponse(201, {"id": "company-1"})
        if url.endswith("/crm/v3/objects/contacts/batch/upsert"):
            return FakeResponse(200, {"results": [{"id": "contact-1"}]})
        if url.endswith("/crm/v4/associations/contact/company/batch/create"):
            return FakeResponse(201, {})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(hs.requests, "post", fake_post)
    error_log = tmp_path / "errors.log"

    count = hs.push_to_hubspot([_prospect()], error_log=error_log)

    assert count == 1
    urls = [c[0] for c in calls]
    assert urls == [
        "https://api.hubapi.com/crm/v3/objects/companies/search",
        "https://api.hubapi.com/crm/v3/objects/companies",
        "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert",
        "https://api.hubapi.com/crm/v4/associations/contact/company/batch/create",
    ]

    # auth header on every call
    for _, headers, _, _ in calls:
        assert headers["Authorization"] == "Bearer svc-key"

    # company search filters on bare domain (scheme + path stripped)
    search_body = calls[0][2]
    assert search_body["filterGroups"][0]["filters"][0]["value"] == "tealdrones.com"

    # company create body
    create_body = calls[1][2]
    assert create_body["properties"]["name"] == "Teal Drones"
    assert create_body["properties"]["domain"] == "tealdrones.com"

    # contact batch upsert body: split name, parsed bare email, idProperty email
    contact_body = calls[2][2]
    assert contact_body["inputs"][0]["idProperty"] == "email"
    assert contact_body["inputs"][0]["id"] == "jane@tealdrones.com"
    props = contact_body["inputs"][0]["properties"]
    assert props["email"] == "jane@tealdrones.com"
    assert props["firstname"] == "Jane"
    assert props["lastname"] == "Doe"
    assert props["jobtitle"] == "VP Engineering"
    assert props["hs_linkedin_url"] == "https://linkedin.com/in/janedoe"

    # association: company then contact, then associate real IDs, primary company type
    assoc_body = calls[3][2]
    assoc_input = assoc_body["inputs"][0]
    assert assoc_input["from"] == {"id": "contact-1"}
    assert assoc_input["to"] == {"id": "company-1"}
    assert assoc_input["types"] == [
        {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 1}
    ]


# ---------- dedupe: existing company found by domain search -> PATCH not POST ----------


def test_push_to_hubspot_updates_existing_company_found_by_domain(monkeypatch, tmp_path):
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "svc-key")
    post_calls = []
    patch_calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        post_calls.append((url, headers, json, timeout))
        if url.endswith("/companies/search"):
            return FakeResponse(200, {"results": [{"id": "company-9"}]})
        if url.endswith("/contacts/batch/upsert"):
            return FakeResponse(200, {"results": [{"id": "contact-1"}]})
        if url.endswith("/associations/contact/company/batch/create"):
            return FakeResponse(201, {})
        raise AssertionError(f"unexpected POST {url}, company create should not be called")

    def fake_patch(url, headers=None, json=None, timeout=None):
        patch_calls.append((url, headers, json, timeout))
        return FakeResponse(200, {"id": "company-9"})

    monkeypatch.setattr(hs.requests, "post", fake_post)
    monkeypatch.setattr(hs.requests, "patch", fake_patch)
    error_log = tmp_path / "errors.log"

    count = hs.push_to_hubspot([_prospect()], error_log=error_log)

    assert count == 1
    assert len(patch_calls) == 1
    assert patch_calls[0][0] == "https://api.hubapi.com/crm/v3/objects/companies/company-9"
    # no POST to create a new company
    create_posts = [c for c in post_calls if c[0].endswith("/companies")]
    assert create_posts == []


# ---------- email "-" miss is skipped, not pushed as a contact ----------


def test_push_to_hubspot_skips_contact_with_missing_email(monkeypatch, tmp_path):
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "svc-key")
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        if url.endswith("/companies/search"):
            return FakeResponse(200, {"results": []})
        if url.endswith("/companies"):
            return FakeResponse(201, {"id": "company-1"})
        raise AssertionError(f"unexpected POST {url} — no contact/association call expected")

    monkeypatch.setattr(hs.requests, "post", fake_post)
    error_log = tmp_path / "errors.log"

    count = hs.push_to_hubspot([_prospect(contact_emails="-")], error_log=error_log)

    assert count == 1
    assert calls == [
        "https://api.hubapi.com/crm/v3/objects/companies/search",
        "https://api.hubapi.com/crm/v3/objects/companies",
    ]


# ---------- HTTP failure on one prospect: logged and skipped, not crashing ----------


def test_push_to_hubspot_http_failure_on_one_prospect_logged_and_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "svc-key")

    def fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/companies/search"):
            return FakeResponse(200, {"results": []})
        if url.endswith("/companies"):
            return FakeResponse(500, text="server error")
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(hs.requests, "post", fake_post)
    error_log = tmp_path / "errors.log"

    count = hs.push_to_hubspot([_prospect()], error_log=error_log)

    assert count == 0
    assert error_log.exists()
    assert "500" in error_log.read_text()


def test_push_to_hubspot_network_error_logged_and_skipped_without_crashing(monkeypatch, tmp_path):
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "svc-key")

    def raise_conn_error(*a, **k):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(hs.requests, "post", raise_conn_error)
    error_log = tmp_path / "errors.log"

    count = hs.push_to_hubspot([_prospect()], error_log=error_log)

    assert count == 0
    assert error_log.exists()
    assert "boom" in error_log.read_text()


def test_push_to_hubspot_one_of_two_prospects_fails_other_still_counted(monkeypatch, tmp_path):
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "svc-key")

    def fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/companies/search"):
            body = {"results": []}
            return FakeResponse(200, body)
        if url.endswith("/companies"):
            # first company create fails, second succeeds
            if not hasattr(fake_post, "_calls"):
                fake_post._calls = 0
            fake_post._calls += 1
            if fake_post._calls == 1:
                return FakeResponse(500, text="server error")
            return FakeResponse(201, {"id": "company-2"})
        if url.endswith("/contacts/batch/upsert"):
            return FakeResponse(200, {"results": [{"id": "contact-1"}]})
        if url.endswith("/associations/contact/company/batch/create"):
            return FakeResponse(201, {})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(hs.requests, "post", fake_post)
    error_log = tmp_path / "errors.log"

    prospects = [
        _prospect(company="Bad Co", website="https://badco.com"),
        _prospect(company="Good Co", website="https://goodco.com"),
    ]
    count = hs.push_to_hubspot(prospects, error_log=error_log)

    assert count == 1
    assert error_log.exists()
    assert "500" in error_log.read_text()


# ---------- multiple contacts split by "; " index, parallel to contact_name ----------


def test_push_to_hubspot_splits_multiple_contacts_by_index(monkeypatch, tmp_path):
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "svc-key")
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, json))
        if url.endswith("/companies/search"):
            return FakeResponse(200, {"results": []})
        if url.endswith("/companies"):
            return FakeResponse(201, {"id": "company-1"})
        if url.endswith("/contacts/batch/upsert"):
            return FakeResponse(
                200, {"results": [{"id": "contact-1"}, {"id": "contact-2"}]}
            )
        if url.endswith("/associations/contact/company/batch/create"):
            return FakeResponse(201, {})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(hs.requests, "post", fake_post)
    error_log = tmp_path / "errors.log"

    prospect = _prospect(
        contact_name="Jane Doe; John Smith",
        contact_title="VP Engineering; CTO",
        contact_linkedin="https://linkedin.com/in/janedoe; https://linkedin.com/in/johnsmith",
        contact_emails="jane@tealdrones.com (verified); john@tealdrones.com (miss)",
    )
    count = hs.push_to_hubspot([prospect], error_log=error_log)

    assert count == 1
    contact_call = next(c for c in calls if c[0].endswith("/contacts/batch/upsert"))
    inputs = contact_call[1]["inputs"]
    # "john@tealdrones.com (miss)" still has a real email address before the
    # "(status)" suffix — only a bare "-" entry is a miss per schema.py's comment.
    assert len(inputs) == 2
    assert inputs[0]["id"] == "jane@tealdrones.com"
    assert inputs[1]["id"] == "john@tealdrones.com"
    assert inputs[1]["properties"]["firstname"] == "John"
    assert inputs[1]["properties"]["lastname"] == "Smith"

    assoc_call = next(
        c for c in calls if c[0].endswith("/associations/contact/company/batch/create")
    )
    assoc_inputs = assoc_call[1]["inputs"]
    assert len(assoc_inputs) == 2
    assert {i["from"]["id"] for i in assoc_inputs} == {"contact-1", "contact-2"}
