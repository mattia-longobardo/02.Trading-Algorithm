"""Difesa da SSRF sui feed RSS configurabili dall'utente.

Il backend scarica questi URL dall'interno della rete Docker e ne indicizza il
contenuto: senza controlli un feed diventerebbe una primitiva di lettura verso
Postgres, Qdrant o i metadata endpoint del cloud.
"""

import pytest

from etoro_bot.knowledge import safe_fetch
from etoro_bot.knowledge.safe_fetch import UnsafeUrlError, assert_public_url


def _resolve_to(monkeypatch, address: str) -> None:
    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", (address, 80))],
    )


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",        # loopback
        "10.1.2.3",         # rete privata
        "172.16.0.5",       # rete privata
        "192.168.1.10",     # rete privata (Docker bridge tipico)
        "169.254.169.254",  # metadata endpoint
        "0.0.0.0",          # unspecified
        "::1",              # loopback IPv6
    ],
)
def test_non_public_addresses_are_refused(monkeypatch, address):
    _resolve_to(monkeypatch, address)
    with pytest.raises(UnsafeUrlError):
        assert_public_url("http://trading-postgres/feed.xml")


def test_public_address_passes(monkeypatch):
    _resolve_to(monkeypatch, "93.184.216.34")
    assert_public_url("https://example.com/rss")


def test_any_private_record_is_enough_to_refuse(monkeypatch):
    """DNS a round-robin: un solo record interno basta a rendere l'host pericoloso."""
    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(UnsafeUrlError):
        assert_public_url("https://rebind.example/rss")


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "gopher://x/1", "ftp://example.com/f", "http://"],
)
def test_non_http_schemes_and_missing_host_are_refused(url):
    with pytest.raises(UnsafeUrlError):
        assert_public_url(url)


def test_unresolvable_host_is_refused(monkeypatch):
    def _boom(*args, **kwargs):
        raise safe_fetch.socket.gaierror("nope")

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", _boom)
    with pytest.raises(UnsafeUrlError):
        assert_public_url("https://inesistente.invalid/rss")


def test_redirect_hops_are_revalidated(monkeypatch):
    """Un 302 verso l'interno non deve passare: ogni tappa è rivalidata."""
    seen: list[str] = []

    def _check(url: str) -> None:
        seen.append(url)
        if "interno" in url:
            raise UnsafeUrlError("host non pubblico")

    class _Opener:
        def open(self, request, timeout=None):
            import urllib.error

            raise urllib.error.HTTPError(
                request.full_url, 302, "Found",
                {"Location": "http://interno.local/segreto"}, None,
            )

    monkeypatch.setattr(safe_fetch, "assert_public_url", _check)
    monkeypatch.setattr(safe_fetch.urllib.request, "build_opener", lambda *a: _Opener())

    with pytest.raises(UnsafeUrlError):
        safe_fetch.fetch_text("https://example.com/rss", user_agent="test")
    assert seen == ["https://example.com/rss", "http://interno.local/segreto"]
