"""Fetch di news da feed RSS/Atom con SOLA stdlib (ElementTree).

Fonti da config/settings.yaml, chiave `news_feeds`: feed `generic` più
template `per_ticker` (con `{ticker}`) applicati alla watchlist. Il parser è
tollerante (RSS 2.0 e Atom), fa strip dell'HTML dai sommari e tiene al massimo
15 item per feed. Un feed che fallisce logga e non interrompe gli altri.
Il download passa da `safe_fetch`, che rifiuta gli host non pubblici: gli URL
dei feed li sceglie l'utente e il fetch parte da dentro la rete Docker.

CLI: python -m etoro_bot.knowledge.fetch_news
"""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

from etoro_bot.config import load_settings
from etoro_bot.knowledge.kb import KnowledgeBase
from etoro_bot.knowledge.safe_fetch import fetch_text

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_S = 10
MAX_ITEMS_PER_FEED = 15
_USER_AGENT = "etoro-bot/3.0 (+https://localhost)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)


def strip_html(text: str) -> str:
    """Rimuove i tag HTML e normalizza spazi ed entità."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(text or ""))).strip()


def _localname(tag: str) -> str:
    """Nome locale di un tag XML, ignorando il namespace ({ns}title → title)."""
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, *names: str) -> str:
    """Testo del primo figlio il cui nome locale è tra `names` (namespace-agnostico)."""
    for child in element:
        if _localname(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _entry_link(element: ET.Element) -> str:
    direct = _child_text(element, "link")
    if direct:
        return direct
    for child in element:
        if _localname(child.tag) == "link" and child.attrib.get("href"):
            return child.attrib["href"]
    return ""


def parse_feed(xml_text: str, source: str, tickers: list[str] | None = None) -> list[dict]:
    """Parser tollerante di RSS 2.0 e Atom → item {text, source, tickers, published_at}.

    `text` = titolo + sommario (HTML rimosso), max MAX_ITEMS_PER_FEED item.
    XML malformato → lista vuota (nessuna eccezione al chiamante).

    Hardening (stdlib only, stessa difesa di defusedxml): i feed che
    dichiarano una DTD (`<!DOCTYPE`) vengono scartati — è il vettore degli
    attacchi XXE e billion-laughs; nessun feed RSS/Atom legittimo la usa.
    """
    if _DOCTYPE_RE.search(xml_text):
        logger.warning("feed %s: DTD (<!DOCTYPE) non ammessa, feed scartato", source)
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("feed %s: XML non parsabile (%s)", source, exc)
        return []

    entries = [el for el in root.iter() if _localname(el.tag) in ("item", "entry")]
    items: list[dict] = []
    for entry in entries[:MAX_ITEMS_PER_FEED]:
        title = strip_html(_child_text(entry, "title"))
        summary = strip_html(_child_text(entry, "description", "summary", "content"))
        text = f"{title}. {summary}" if title and summary else (title or summary)
        if not text:
            continue
        items.append(
            {
                "text": text,
                "source": source,
                "tickers": list(tickers or []),
                "published_at": _child_text(entry, "pubDate", "published", "updated"),
                "url": _entry_link(entry),
            }
        )
    return items


def _fetch_url(url: str) -> str:
    """Scarica un feed. Gli URL arrivano dalla UI: il fetcher rifiuta gli host
    non pubblici, così un feed non può diventare una sonda sulla rete interna."""
    return fetch_text(url, user_agent=_USER_AGENT)


def _feed_source(url: str) -> str:
    return urlparse(url).hostname or url


def fetch_all(settings: dict[str, Any] | None = None) -> list[dict]:
    """Scarica tutti i feed configurati; un feed che fallisce logga e continua."""
    cfg = settings if settings is not None else load_settings()
    feeds_cfg = cfg.get("news_feeds") or {}
    watchlist = [str(t) for t in (cfg.get("watchlist") or [])]

    plan: list[tuple[str, list[str]]] = [(url, []) for url in (feeds_cfg.get("generic") or [])]
    for template in feeds_cfg.get("per_ticker") or []:
        plan.extend((template.format(ticker=ticker), [ticker]) for ticker in watchlist)

    items: list[dict] = []
    for url, tickers in plan:
        try:
            xml_text = _fetch_url(url)
        except Exception as exc:
            logger.warning("feed %s: fetch fallito (%s), continuo con gli altri", url, exc)
            continue
        items.extend(parse_feed(xml_text, source=_feed_source(url), tickers=tickers))
    return items


def fetch_and_index(kb: KnowledgeBase) -> int:
    """Scarica i feed e indicizza gli item in `news_kb`; ritorna quanti indicizzati."""
    items = fetch_all()
    if not items:
        return 0
    kb.ensure_collections()
    return kb.add_news(items)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    indexed = fetch_and_index(KnowledgeBase())
    print(f"news indicizzate: {indexed}")
