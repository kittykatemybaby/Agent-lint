"""Embedding support for Project Brain — DeepSeek API backend.

Phase 1: Replace keyword similarity with embedding-based semantic search.
Uses DeepSeek embeddings API (same API key as chat). Batch mode for efficiency.
"""

import json
import os
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime

BRAIN_DB = Path(__file__).parent / "project_brain.db"
EMBED_CACHE = Path(__file__).parent / ".embed_cache.json"


def _get_deepseek_client():
    """Get DeepSeek client for embeddings."""
    import httpx
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)


def embed_text(text: str) -> list[float] | None:
    """Get embedding. Uses local model ($0) first, falls back to API."""
    # Local model — $0, fast, offline
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2", cache_folder="/opt/data/.cache/sbert")
        return model.encode(text[:8000]).tolist()
    except Exception:
        pass
    # Fallback: DeepSeek API
    try:
        client = _get_deepseek_client()
        resp = client.post("/v1/embeddings", json={"model": "deepseek-chat", "input": text[:8000]})
        data = resp.json()
        if data.get("data"):
            return data["data"][0]["embedding"]
    except Exception:
        pass
    return None


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Batch embed multiple texts. Saves API cost."""
    if not texts:
        return []
    try:
        client = _get_deepseek_client()
        resp = client.post("/v1/embeddings", json={
            "model": "deepseek-chat",
            "input": [t[:8000] for t in texts],
        })
        data = resp.json()
        return [d["embedding"] for d in data.get("data", [])]
    except Exception:
        return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def store_embedding(record_id: int, embedding: list[float]):
    """Store embedding in SQLite."""
    db = sqlite3.connect(str(BRAIN_DB))
    db.execute(
        "UPDATE records SET embedding = ? WHERE id = ?",
        (json.dumps(embedding), record_id),
    )
    db.commit()
    db.close()


def get_unembedded_records(limit: int = 50) -> list[dict]:
    """Get records that don't have embeddings yet."""
    db = sqlite3.connect(str(BRAIN_DB))
    rows = db.execute(
        "SELECT id, context, root_cause FROM records WHERE embedding IS NULL LIMIT ?",
        (limit,),
    ).fetchall()
    db.close()
    return [{"id": r[0], "context": r[1] or "", "root_cause": r[2] or ""} for r in rows]


def build_embedding_index():
    """Batch embed all unembedded records."""
    records = get_unembedded_records(50)
    if not records:
        return 0

    texts = [f"{r['context']} {r['root_cause']}" for r in records]
    embeddings = embed_batch(texts)

    count = 0
    for r, emb in zip(records, embeddings):
        if emb:
            store_embedding(r["id"], emb)
            count += 1

    return count


def embedding_search(query: str, record_types: list[str] = None, top_k: int = 5) -> list[dict]:
    """Search records using embedding similarity + recency decay."""
    query_emb = embed_text(query)
    if not query_emb:
        return []  # fall back to keyword search

    from project_brain import _get_db, _recency_decay, _row_to_dict

    db = _get_db()
    type_filter = " AND record_type IN ({})".format(','.join('?'*len(record_types))) if record_types else ""
    params = tuple(record_types) if record_types else ()

    rows = db.execute(
        f"SELECT id, record_type, context, root_cause, fix, reusability, created_at, embedding FROM records WHERE embedding IS NOT NULL{type_filter} ORDER BY created_at DESC LIMIT 200",
        params,
    ).fetchall()
    db.close()

    scored = []
    for r in rows:
        stored_emb = json.loads(r[7]) if r[7] else None
        if not stored_emb:
            continue

        semantic = cosine_similarity(query_emb, stored_emb)
        recency = _recency_decay(r[6])
        score = 0.5 * semantic + 0.2 * max(semantic, 0) + 0.3 * recency
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {**_row_to_dict(r, ["id","record_type","context","root_cause","fix","reusability","created_at"]), "score": round(s, 3)}
        for s, r in scored[:top_k]
    ]
