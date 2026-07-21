"""Ingestione manuale di documenti .md/.txt nella knowledge base.

I ticker impattati li **rileva il bot**: ogni chunk viene analizzato da
`knowledge.tickers.detect_tickers` e associato ai titoli dell'universo
investibile che vi compaiono (simbolo o nome societario). L'header opzionale
`tickers: AAPL, MSFT` in prima riga di un file resta valido per l'ingestione da
riga di comando e si unisce a quanto rilevato; l'API non accetta più ticker
indicati a mano, perché è il documento a dire quali titoli tocca.

Il testo è spezzato in chunk da ~1500 caratteri sui confini di paragrafo.

CLI: python -m etoro_bot.knowledge.ingest ./knowledge_base
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from etoro_bot.knowledge.kb import KnowledgeBase
from etoro_bot.knowledge.tickers import detect_tickers

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1500
SUPPORTED_SUFFIXES = (".md", ".txt")
MAX_UPLOAD_BYTES = 20_000_000

_TICKERS_RE = re.compile(r"^tickers\s*:\s*(.+)$", re.IGNORECASE)


def parse_document(text: str) -> tuple[list[str], str]:
    """Estrae l'header opzionale `tickers: AAPL, MSFT` dalla prima riga.

    Ritorna (tickers, corpo senza header). Senza header: ([], testo intero).
    """
    lines = text.splitlines()
    if lines:
        match = _TICKERS_RE.match(lines[0].strip())
        if match:
            tickers = [t.strip().upper() for t in match.group(1).split(",") if t.strip()]
            return tickers, "\n".join(lines[1:]).strip()
    return [], text.strip()


def chunk_text(text: str, max_chars: int = CHUNK_SIZE) -> list[str]:
    """Spezza il testo in chunk da ~max_chars caratteri sui confini di paragrafo.

    Un singolo paragrafo più lungo di max_chars diventa un chunk a sé (non
    viene troncato: meglio un chunk lungo che una frase spezzata).
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True)
class IngestOutcome:
    """Esito di un'ingestione: quanti chunk e quali titoli sono risultati toccati."""

    chunks: int
    tickers: list[str]


def _merge(*groups: list[str]) -> list[str]:
    """Unione ordinata e senza duplicati, preservando l'ordine di comparsa."""
    merged: list[str] = []
    for group in groups:
        for ticker in group:
            symbol = ticker.strip().upper()
            if symbol and symbol not in merged:
                merged.append(symbol)
    return merged


def _build_items(body: str, source: str, manual: list[str] | None) -> tuple[list[dict], list[str]]:
    """Chunk + ticker per chunk: rilevati dal testo, uniti a quelli indicati a mano.

    Il rilevamento è per chunk, non per documento: in un report su più società
    ogni pezzo resta associato solo ai titoli di cui parla davvero, altrimenti
    una ricerca su un titolo restituirebbe l'intero documento.
    """
    manual = manual or []
    items: list[dict] = []
    document_tickers: list[str] = []
    for chunk in chunk_text(body):
        tickers = _merge(manual, detect_tickers(chunk))
        document_tickers = _merge(document_tickers, tickers)
        items.append(
            {"text": chunk, "source": source, "tickers": tickers, "published_at": ""}
        )
    return items, document_tickers


def ingest_text(text: str, kb: KnowledgeBase | None = None) -> IngestOutcome:
    """Ingerisce testo incollato; i ticker sono dedotti dal contenuto."""
    kb = kb or KnowledgeBase()
    header_tickers, body = parse_document(text)
    kb.ensure_collections()
    items, detected = _build_items(body, "manual", header_tickers)
    return IngestOutcome(chunks=kb.add_news(items), tickers=detected)


def ingest_upload(
    filename: str, content: bytes, kb: KnowledgeBase | None = None
) -> IngestOutcome:
    """Ingerisce un file caricato via API; i ticker sono dedotti dal contenuto.

    Supporta .pdf/.docx/.pptx/.xlsx oltre a .md/.txt, tramite `parsers.extract_text`.
    """
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("file troppo grande (max 20MB)")

    from etoro_bot.knowledge.parsers import extract_text

    text = extract_text(filename, content)
    kb = kb or KnowledgeBase()
    header_tickers, body = parse_document(text)
    kb.ensure_collections()
    items, detected = _build_items(body, filename, header_tickers)
    return IngestOutcome(chunks=kb.add_news(items), tickers=detected)


def ingest_path(path: str | Path, kb: KnowledgeBase) -> int:
    """Ingerisce un file o una directory (.md/.txt); ritorna i chunk indicizzati."""
    base = Path(path)
    if base.is_dir():
        files = sorted(p for p in base.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES)
    elif base.is_file():
        files = [base]
    else:
        logger.warning("percorso %s inesistente: nulla da ingerire", base)
        return 0

    kb.ensure_collections()
    total = 0
    for file in files:
        try:
            header_tickers, body = parse_document(file.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("file %s illeggibile (%s), continuo con gli altri", file, exc)
            continue
        items, detected = _build_items(body, file.name, header_tickers)
        indexed = kb.add_news(items)
        total += indexed
        logger.info(
            "%s: %d chunk indicizzati, titoli rilevati: %s",
            file.name,
            indexed,
            ", ".join(detected) or "nessuno",
        )
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ingestione manuale nella knowledge base")
    parser.add_argument("path", nargs="?", default="./knowledge_base",
                        help="file o directory .md/.txt (default: ./knowledge_base)")
    args = parser.parse_args()
    print(f"chunk indicizzati: {ingest_path(args.path, KnowledgeBase())}")
