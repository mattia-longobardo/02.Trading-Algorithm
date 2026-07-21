"""Fetch HTTP con difesa da SSRF, per gli URL che decide l'utente.

I feed RSS sono configurabili dalla UI e il backend li scarica *lui*, dall'interno
della rete Docker: senza controlli un URL come `http://trading-postgres:5432/` o
`http://169.254.169.254/` diventerebbe una primitiva di lettura sulla rete
interna, per giunta con il risultato indicizzato nella knowledge base e quindi
leggibile dalla pagina News.

La difesa è sulla *destinazione risolta*, non sulla stringa: si risolve il
nome, si scartano gli indirizzi non pubblici e si ripete il controllo a ogni
redirect (un 302 verso 127.0.0.1 aggirerebbe un controllo fatto solo all'inizio).
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse

FETCH_TIMEOUT_S = 10
MAX_REDIRECTS = 3
MAX_BYTES = 5_000_000


class UnsafeUrlError(ValueError):
    """URL che punta fuori dalla rete pubblica: rifiutato prima di connettersi."""


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_public_url(url: str) -> None:
    """Rifiuta schemi diversi da http(s) e host che risolvono fuori da Internet."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"schema non ammesso: {url}")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError(f"URL senza host: {url}")

    try:
        resolved = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"host non risolvibile: {host}") from exc

    addresses = {info[4][0] for info in resolved}
    if not addresses:
        raise UnsafeUrlError(f"host non risolvibile: {host}")
    # Tutti gli indirizzi devono essere pubblici: basta un record privato
    # perché il round-robin del DNS possa portarci sulla rete interna.
    for address in addresses:
        if not _is_public(address):
            raise UnsafeUrlError(f"host non pubblico: {host} → {address}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """I redirect li seguiamo a mano, per poter rivalidare ogni tappa."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def fetch_text(url: str, *, user_agent: str, timeout: int = FETCH_TIMEOUT_S) -> str:
    """Scarica `url` come testo, validando l'URL iniziale e ogni redirect."""
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        assert_public_url(current)
        request = urllib.request.Request(current, headers={"User-Agent": user_agent})
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.read(MAX_BYTES).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code not in (301, 302, 303, 307, 308) or not location:
                raise
            current = urljoin(current, location)
    raise UnsafeUrlError(f"troppi redirect: {url}")
