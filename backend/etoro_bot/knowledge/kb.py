"""RAG su Qdrant + fastembed (BAAI/bge-small-en-v1.5, 384 dim, cosine).

Gli embeddings sono calcolati localmente (nessuna API key). Le librerie
`qdrant-client` e `fastembed` (extra `rag`) sono importate SOLO dentro la
classe: se mancano, o se Qdrant è irraggiungibile, la KnowledgeBase entra in
modalità degradata — ogni metodo ritorna vuoto e logga un warning una volta
sola. La KB è un'aggiunta, mai un requisito.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:6333"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
VECTOR_SIZE = 384

NEWS_COLLECTION = "news_kb"
TRADE_MEMORY_COLLECTION = "trade_memory"

# Decadimento temporale delle news in ricerca: il peso dimezza ogni half-life.
DEFAULT_NEWS_HALF_LIFE_DAYS = 7.0
# Punti indicizzati prima dell'introduzione di published_ts: età convenzionale.
_LEGACY_AGE_HALF_LIVES = 2.0


def parse_published_ts(value: str) -> float | None:
    """Timestamp epoch da una data RSS (RFC 822) o Atom/ISO 8601; None se illeggibile."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def news_payload(item: dict, now: float | None = None) -> dict:
    """Payload Qdrant di un item: testo, fonte, ticker, tipo e timestamp.

    `kind` distingue le news dei feed ("news", soggette a decadimento e purge)
    dai documenti caricati dall'utente ("document", che non scadono).
    Per le news senza data pubblicazione si usa il momento dell'indicizzazione:
    un feed appena scaricato è per definizione recente.
    """
    now = now if now is not None else time.time()
    kind = str(item.get("kind") or "news")
    published_ts = parse_published_ts(str(item.get("published_at") or ""))
    if published_ts is None and kind == "news":
        published_ts = now
    return {
        "text": str(item.get("text") or "").strip(),
        "source": item.get("source", ""),
        "tickers": list(item.get("tickers") or []),
        "published_at": item.get("published_at", ""),
        "kind": kind,
        "published_ts": published_ts,
        "indexed_ts": now,
    }


def recency_weight(
    payload: dict, half_life_days: float, now: float | None = None
) -> float:
    """Peso ∈ (0,1] del punto in ricerca: le news vecchie contano meno.

    I documenti utente non decadono (peso 1). Le news senza alcun timestamp
    (indicizzate prima di questa versione) ricevono un'età convenzionale di
    due half-life, così non sovrastano le notizie datate correttamente.
    """
    if str(payload.get("kind") or "news") == "document":
        return 1.0
    now = now if now is not None else time.time()
    half_life = max(float(half_life_days), 0.1)
    ts = payload.get("published_ts") or payload.get("indexed_ts")
    if ts is None:
        return 0.5 ** _LEGACY_AGE_HALF_LIVES
    age_days = max(0.0, (now - float(ts)) / 86400.0)
    return 0.5 ** (age_days / half_life)


def rerank_by_recency(
    results: list[dict], half_life_days: float, now: float | None = None
) -> list[dict]:
    """Riordina i risultati per score semantico × peso di recency.

    `score` diventa lo score effettivo (usato dai chiamanti per l'ordine);
    l'originale resta in `raw_score`, il peso in `recency_weight`.
    """
    reranked = []
    for item in results:
        weight = recency_weight(item, half_life_days, now)
        reranked.append(
            {
                **item,
                "raw_score": item.get("score"),
                "recency_weight": round(weight, 4),
                "score": (item.get("score") or 0.0) * weight,
            }
        )
    reranked.sort(key=lambda r: r["score"], reverse=True)
    return reranked


def point_id_for_text(text: str) -> str:
    """Id punto deterministico dal testo (SHA1 → UUID): stesso testo, stesso id.

    Qdrant accetta come id solo UUID o interi: i primi 128 bit dello SHA1 del
    testo vengono formattati come UUID. La stabilità garantisce il dedup.
    """
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return str(uuid.UUID(digest[:32]))


class KnowledgeBase:
    """Accesso alle collection Qdrant `news_kb` e `trade_memory`.

    In modalità degradata (`available = False`) ogni metodo è un no-op che
    ritorna vuoto: il chiamante non deve mai gestire eccezioni della KB.
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get("QDRANT_URL", DEFAULT_URL)
        self.available = False
        self._warned = False
        self._client: Any = None
        self._embedder: Any = None
        try:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self.url, timeout=5)
            self._client.get_collections()  # verifica di connettività
            self.available = True
        except Exception as exc:  # ImportError, connessione rifiutata, URL invalido…
            self._degrade(f"Qdrant non disponibile su {self.url}: {exc}")

    # -- infrastruttura interna -------------------------------------------------

    def _degrade(self, reason: str) -> None:
        """Passa (una volta sola) in modalità degradata, senza sollevare."""
        self.available = False
        if not self._warned:
            self._warned = True
            logger.warning("KnowledgeBase in modalità degradata: %s", reason)

    def _embed(self, text: str) -> list[float] | None:
        """Embedding locale via fastembed; None se il modello non è disponibile."""
        try:
            if self._embedder is None:
                from fastembed import TextEmbedding

                cache_dir = os.environ.get("FASTEMBED_CACHE_DIR", "/app/state/fastembed_cache")
                Path(cache_dir).mkdir(parents=True, exist_ok=True)
                self._embedder = TextEmbedding(model_name=EMBEDDING_MODEL, cache_dir=cache_dir)
            return list(next(iter(self._embedder.embed([text]))))
        except Exception as exc:
            self._degrade(f"fastembed non disponibile: {exc}")
            return None

    def _search(
        self,
        collection: str,
        query: str,
        limit: int,
        query_filter: Any = None,
    ) -> list[dict]:
        if not self.available:
            self._degrade("ricerca ignorata (KB non disponibile)")
            return []
        vector = self._embed(query)
        if vector is None:
            return []
        try:
            try:
                points = self._client.query_points(
                    collection, query=vector, limit=limit, query_filter=query_filter
                ).points
            except AttributeError:  # qdrant-client < 1.10
                points = self._client.search(
                    collection_name=collection,
                    query_vector=vector,
                    limit=limit,
                    query_filter=query_filter,
                )
            return [{**(p.payload or {}), "score": p.score} for p in points]
        except Exception as exc:
            self._degrade(f"ricerca su {collection} fallita: {exc}")
            return []

    def _upsert(self, collection: str, points: list[Any]) -> None:
        try:
            self._client.upsert(collection_name=collection, points=points)
        except Exception as exc:
            self._degrade(f"upsert su {collection} fallito: {exc}")

    # -- API pubblica -----------------------------------------------------------

    def ensure_collections(self) -> None:
        """Crea `news_kb` e `trade_memory` se assenti (384 dim, cosine)."""
        if not self.available:
            self._degrade("ensure_collections ignorata (KB non disponibile)")
            return
        try:
            from qdrant_client import models

            for name in (NEWS_COLLECTION, TRADE_MEMORY_COLLECTION):
                if not self._client.collection_exists(name):
                    self._client.create_collection(
                        collection_name=name,
                        vectors_config=models.VectorParams(
                            size=VECTOR_SIZE, distance=models.Distance.COSINE
                        ),
                    )
        except Exception as exc:
            self._degrade(f"creazione collection fallita: {exc}")

    def add_news(self, items: list[dict]) -> int:
        """Indicizza news in `news_kb`; payload {text, source, tickers, published_at}.

        L'id del punto è l'hash del testo: reindicizzare lo stesso item è un
        upsert idempotente (dedup). Ritorna il numero di item indicizzati.
        """
        if not self.available or not items:
            if not self.available:
                self._degrade("add_news ignorata (KB non disponibile)")
            return 0
        try:
            from qdrant_client import models
        except Exception as exc:
            self._degrade(f"qdrant-client non disponibile: {exc}")
            return 0
        now = time.time()
        points = []
        for item in items:
            payload = news_payload(item, now)
            if not payload["text"]:
                continue
            vector = self._embed(payload["text"])
            if vector is None:
                return 0
            points.append(
                models.PointStruct(
                    id=point_id_for_text(payload["text"]),
                    vector=vector,
                    payload=payload,
                )
            )
        if points:
            self._upsert(NEWS_COLLECTION, points)
        return len(points) if self.available else 0

    def search_news(
        self,
        query: str,
        tickers: list[str] | None = None,
        limit: int = 5,
        half_life_days: float = DEFAULT_NEWS_HALF_LIFE_DAYS,
    ) -> list[dict]:
        """Ricerca semantica in `news_kb`, filtrata per ticker se richiesto.

        Le news vecchie contano meno: si recupera un pool più ampio e lo si
        riordina per score × peso di recency (dimezza ogni `half_life_days`).
        I documenti caricati dall'utente non decadono.
        """
        query_filter = None
        if tickers:
            try:
                from qdrant_client import models

                query_filter = models.Filter(
                    must=[models.FieldCondition(key="tickers", match=models.MatchAny(any=tickers))]
                )
            except Exception as exc:
                self._degrade(f"qdrant-client non disponibile: {exc}")
                return []
        pool = self._search(NEWS_COLLECTION, query, max(limit * 4, 20), query_filter)
        return rerank_by_recency(pool, half_life_days)[:limit]

    def purge_old_news(self, max_age_days: float) -> int:
        """Elimina da `news_kb` le news più vecchie di `max_age_days` giorni.

        Tocca SOLO i punti `kind == "news"` con `published_ts` sotto la soglia:
        i documenti caricati dall'utente (e i punti legacy senza timestamp)
        restano. Ritorna quanti punti sono stati eliminati; 0 in degradata.
        """
        if not self.available:
            self._degrade("purge_old_news ignorata (KB non disponibile)")
            return 0
        try:
            from qdrant_client import models

            cutoff = time.time() - float(max_age_days) * 86400.0
            old_filter = models.Filter(
                must=[
                    models.FieldCondition(key="kind", match=models.MatchValue(value="news")),
                    models.FieldCondition(key="published_ts", range=models.Range(lt=cutoff)),
                ]
            )
            if not self._client.collection_exists(NEWS_COLLECTION):
                return 0
            count = self._client.count(
                NEWS_COLLECTION, count_filter=old_filter, exact=True
            ).count
            if count:
                self._client.delete(
                    collection_name=NEWS_COLLECTION,
                    points_selector=models.FilterSelector(filter=old_filter),
                )
                logger.info("news_kb: eliminate %d news più vecchie di %s giorni",
                            count, max_age_days)
            return int(count)
        except Exception as exc:
            self._degrade(f"purge news fallita: {exc}")
            return 0

    def add_trade_memory(self, text: str, payload: dict) -> None:
        """Indicizza un trade chiuso (tesi + esito + pnl) in `trade_memory`."""
        if not self.available:
            self._degrade("add_trade_memory ignorata (KB non disponibile)")
            return
        vector = self._embed(text)
        if vector is None:
            return
        try:
            from qdrant_client import models
        except Exception as exc:
            self._degrade(f"qdrant-client non disponibile: {exc}")
            return
        self._upsert(
            TRADE_MEMORY_COLLECTION,
            [
                models.PointStruct(
                    id=point_id_for_text(text),
                    vector=vector,
                    payload={"text": text, **payload},
                )
            ],
        )

    def search_trade_memory(self, query: str, limit: int = 3) -> list[dict]:
        """Recupera i trade passati più simili al setup corrente."""
        return self._search(TRADE_MEMORY_COLLECTION, query, limit)

    def status(self) -> dict:
        """Stato per la pagina Knowledge: {qdrant_up, collections: {name: count}}."""
        if not self.available:
            return {"qdrant_up": False, "collections": {}}
        counts: dict[str, int] = {}
        try:
            for name in (NEWS_COLLECTION, TRADE_MEMORY_COLLECTION):
                if self._client.collection_exists(name):
                    counts[name] = self._client.count(name, exact=True).count
                else:
                    counts[name] = 0
            return {"qdrant_up": True, "collections": counts}
        except Exception as exc:
            self._degrade(f"status fallito: {exc}")
            return {"qdrant_up": False, "collections": {}}
