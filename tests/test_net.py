"""SSRF guard: a URL is only fetchable when it resolves to a public address.

Strix run gtm-helper_eea7 (2026-08-10) reported CWE-918: `Brief.urls` / `Prospect.website`
are operator/discovery input that reached the scrapers after only a DNS-existence check,
so `http://127.0.0.1:8080/` or a hostname pointing at 169.254.169.254 was fetched and its
body returned into the run's markdown.
"""
import pytest

from gtm.net import BlockedTarget, assert_public_url, is_public_url


def public(host):
    return "93.184.216.34"  # example.com, globally routable


def test_public_host_is_allowed():
    assert is_public_url("https://tealdrones.com/products", lookup=public) is True


def test_loopback_name_is_blocked():
    assert is_public_url("http://localhost:8080/admin", lookup=lambda h: "127.0.0.1") is False


def test_loopback_literal_is_blocked_without_any_lookup():
    def no_dns(host):
        raise AssertionError("an IP literal must never be sent to DNS")

    assert is_public_url("http://127.0.0.1/", lookup=no_dns) is False


def test_ipv6_loopback_literal_is_blocked():
    assert is_public_url("http://[::1]/", lookup=public) is False


@pytest.mark.parametrize("ip", ["10.0.0.5", "172.16.0.1", "192.168.1.1"])
def test_rfc1918_addresses_are_blocked(ip):
    assert is_public_url("https://intranet.example/", lookup=lambda h: ip) is False


def test_link_local_metadata_address_is_blocked():
    assert is_public_url("https://metadata.example/", lookup=lambda h: "169.254.169.254") is False


def test_a_public_name_that_resolves_to_loopback_is_blocked():
    """DNS rebinding in its cheapest form: the name looks external, the answer doesn't."""
    assert is_public_url("https://evil.example.com/", lookup=lambda h: "127.0.0.1") is False


def test_non_http_scheme_is_blocked():
    assert is_public_url("file:///etc/passwd", lookup=public) is False


def test_url_without_a_host_is_blocked():
    assert is_public_url("not-a-url", lookup=public) is False


def test_dead_domain_is_blocked():
    def dead(host):
        raise OSError("NXDOMAIN")

    assert is_public_url("https://pdw.aero/", lookup=dead) is False


def test_assert_public_url_raises_blocked_target_for_internal_hosts():
    with pytest.raises(BlockedTarget, match="127.0.0.1"):
        assert_public_url("http://localhost/", lookup=lambda h: "127.0.0.1")


def test_assert_public_url_returns_none_for_a_public_host():
    assert assert_public_url("https://tealdrones.com", lookup=public) is None
