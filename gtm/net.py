"""Outbound-request guard: a scrape target must resolve to a public address.

2026-08-10, Strix run gtm-helper_eea7 (CWE-918). Scrape targets are untrusted input —
`Brief.urls` is whatever the operator pasted and `Prospect.website` is whatever Serper
discovery returned — and the only check standing in front of them was `resolves()`, which
asked "does this name exist in DNS" and nothing else. `http://127.0.0.1:8080/`, an internal
hostname, or a public name answering with 169.254.169.254 all passed, got fetched, and had
their body written into the run's markdown and the extraction prompt.

The check is on the *resolved address*, not the hostname: blocking the literal `localhost`
alone is theatre, because a name is free to answer 127.0.0.1. `lookup` is injected so the
test suite (and the fixtures) never touch real DNS.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}

# Module-level so conftest can swap it for the whole suite; call sites that mean to
# exercise the guard pass `lookup=` explicitly.
LOOKUP = socket.gethostbyname


class BlockedTarget(Exception):
    """Raised for a URL that is not a public http(s) destination."""


def _address_of(host: str, lookup) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The host's IP: parsed directly when it is already a literal (no DNS round-trip
    for `http://127.0.0.1/`), resolved otherwise. None = unusable target."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(lookup(host))
    except (OSError, ValueError):
        return None


def is_public_url(url: str, *, lookup=None) -> bool:
    """True only for an http(s) URL whose host resolves to a globally routable address.

    False covers every reason we would refuse to fetch: a non-http scheme, no host, a
    host that does not resolve (the old dead-domain case, still free to check), and any
    loopback / RFC1918 / link-local / reserved answer.
    """
    lookup = lookup or LOOKUP
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False
    try:
        host = parsed.hostname  # strips :port and the [] around an IPv6 literal
    except ValueError:  # malformed IPv6 literal
        return False
    if not host:
        return False
    ip = _address_of(host, lookup)
    if ip is None:
        return False
    return bool(ip.is_global)


def assert_public_url(url: str, *, lookup=None) -> None:
    """is_public_url as a guard clause. Raises BlockedTarget naming the address, so an
    operator reading data/errors.log can see *why* a target was refused."""
    lookup = lookup or LOOKUP
    if is_public_url(url, lookup=lookup):
        return
    parsed = urlparse(url)
    try:
        host = parsed.hostname or ""
    except ValueError:
        host = ""
    ip = _address_of(host, lookup) if host else None
    detail = f"{host} -> {ip}" if ip is not None else (host or url)
    raise BlockedTarget(f"blocked target {detail}: not a public http(s) destination")
