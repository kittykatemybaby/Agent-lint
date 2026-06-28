"""Memory Verification Layer — anti-hallucination, anti-drift.

Upgrades Project Brain with:
  1. Status: verified / unverified / rejected
  2. Confidence-scored retrieval
  3. Source trace (which record proved this)
  4. Model version tag + timestamp on every record
  5. Hybrid answer format: retrieved memory + fresh reasoning
"""

import sqlite3
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

BRAIN_DB = Path(__file__).parent / "project_brain.db"


class MemoryStatus(str, Enum):
    VERIFIED = "verified"       # External evidence confirmed. Assume TRUTH.
    UNVERIFIED = "unverified"   # Agent observed, not confirmed. Use with LOW confidence.
    REJECTED = "rejected"       # Proven wrong. Never retrieve. Keep for audit.
    STALE = "stale"             # Verified but too old. Needs re-verification.


# ── Schema Migration ──────────────────────────────────────────────

def migrate_schema():
    db = sqlite3.connect(str(BRAIN_DB))
    
    # Add status column
    try:
        db.execute("ALTER TABLE records ADD COLUMN status TEXT DEFAULT 'unverified'")
    except sqlite3.OperationalError:
        pass  # Already exists

    # Add verification metadata
    try:
        db.execute("ALTER TABLE records ADD COLUMN model_version TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE records ADD COLUMN verified_by TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE records ADD COLUMN verified_at TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE records ADD COLUMN source_trace TEXT DEFAULT ''")  # JSON: [parent_record_id, ...]
    except sqlite3.OperationalError:
        pass

    # Source trace table — tracks which records derived from which
    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_lineage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_id INTEGER NOT NULL,
            parent_id INTEGER NOT NULL,
            relationship TEXT DEFAULT 'derived_from',
            created_at TEXT NOT NULL
        )
    """)

    db.commit()
    db.close()


migrate_schema()


# ── Verification Operations ───────────────────────────────────────

def verify_record(record_id: int, verified_by: str = "critic", model_version: str = ""):
    """Mark a record as verified by external evidence. Once verified, LLM assumes TRUTH."""
    db = sqlite3.connect(str(BRAIN_DB))
    db.execute("""
        UPDATE records SET status = ?, verified_by = ?, verified_at = ?, model_version = ?
        WHERE id = ?
    """, (MemoryStatus.VERIFIED, verified_by, datetime.now().isoformat(), model_version, record_id))
    db.commit()
    db.close()


def reject_record(record_id: int, verified_by: str = "critic"):
    """Mark a record as rejected. Never retrieved. Kept for audit."""
    db = sqlite3.connect(str(BRAIN_DB))
    db.execute("""
        UPDATE records SET status = ?, verified_by = ?, verified_at = ?
        WHERE id = ?
    """, (MemoryStatus.REJECTED, verified_by, datetime.now().isoformat()))
    db.commit()
    db.close()


def mark_stale(record_id: int):
    """Mark a verified record as stale — too old, needs re-verification."""
    db = sqlite3.connect(str(BRAIN_DB))
    db.execute("UPDATE records SET status = ? WHERE id = ?", (MemoryStatus.STALE, record_id))
    db.commit()
    db.close()


def auto_stale_check(days_threshold: int = 30):
    """Automatically mark old verified records as stale."""
    db = sqlite3.connect(str(BRAIN_DB))
    cutoff = (datetime.now() - timedelta(days=days_threshold)).isoformat()
    count = db.execute(
        "UPDATE records SET status = ? WHERE status = ? AND verified_at < ?",
        (MemoryStatus.STALE, MemoryStatus.VERIFIED, cutoff)
    ).rowcount
    db.commit()
    db.close()
    return count


def set_source_trace(record_id: int, parent_ids: list[int]):
    """Record lineage: this record was derived from these parent records."""
    db = sqlite3.connect(str(BRAIN_DB))
    # Store in record
    db.execute("UPDATE records SET source_trace = ? WHERE id = ?",
               (json.dumps(parent_ids), record_id))
    # Store in lineage table
    now = datetime.now().isoformat()
    for pid in parent_ids:
        db.execute("""
            INSERT INTO memory_lineage (child_id, parent_id, created_at)
            VALUES (?, ?, ?)
        """, (record_id, pid, now))
    db.commit()
    db.close()


# ── Confidence-Weighted Retrieval ─────────────────────────────────

def _status_confidence(status: str) -> float:
    return {
        MemoryStatus.VERIFIED: 1.0,    # Assume truth
        MemoryStatus.UNVERIFIED: 0.3,  # Observed, not confirmed
        MemoryStatus.STALE: 0.4,       # Was verified, now old
        MemoryStatus.REJECTED: 0.0,    # Never retrieve
    }.get(status, 0.3)


def confidence_weighted_retrieval(
    query: str,
    record_types: list[str] = None,
    top_k: int = 5,
    min_status_confidence: float = 0.0,
) -> list[dict]:
    """Retrieve with confidence weighting.

    score = 0.5*semantic + 0.2*recency + 0.3*status_confidence

    Rejected records (confidence=0) are ALWAYS excluded.
    Unverified records come with low confidence by default.
    Verified records are assumed TRUE and get full weight.
    """
    from project_brain import _get_db, _simple_similarity, _recency_decay, _row_to_dict

    db = _get_db()
    type_filter = " AND record_type IN ({})".format(','.join('?'*len(record_types))) if record_types else ""
    params = tuple(record_types) if record_types else ()

    cols = ["id","record_type","context","root_cause","fix","reusability","created_at","status","verified_by","model_version","source_trace"]
    rows = db.execute(
        f"SELECT {','.join(cols)} FROM records WHERE status != 'rejected'{type_filter} ORDER BY created_at DESC LIMIT 200",
        params,
    ).fetchall()
    db.close()

    scored = []
    for r in rows:
        record_type = r[1]
        context = r[2] or ""
        root_cause = r[3] or ""
        created_at = r[6]
        status = r[7] or "unverified"

        status_conf = _status_confidence(status)
        if status_conf < min_status_confidence:
            continue

        semantic = _simple_similarity(query, f"{context} {root_cause}")
        recency = _recency_decay(created_at)

        score = 0.5 * semantic + 0.2 * recency + 0.3 * status_conf

        record = _row_to_dict(r, cols)
        record["confidence"] = {
            "score": round(score, 3),
            "semantic": round(semantic, 3),
            "recency": round(recency, 3),
            "status_confidence": round(status_conf, 2),
        }
        scored.append((score, record))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:top_k]]


# ── Hybrid Answer Format ──────────────────────────────────────────

def hybrid_answer(query: str, fresh_reasoning: str, top_k: int = 3) -> dict:
    """Enforce hybrid format: must include retrieved memory + fresh reasoning.

    This prevents pure 'remembered' answers and pure 'from-scratch' reasoning.
    Both are required.
    """
    memories = confidence_weighted_retrieval(query, top_k=top_k, min_status_confidence=0.1)

    verified_sources = [m for m in memories if m.get("status") == MemoryStatus.VERIFIED]
    unverified_sources = [m for m in memories if m.get("status") != MemoryStatus.VERIFIED]

    return {
        "query": query,
        "retrieved_memory": {
            "verified": [
                {"context": m["context"][:100], "fix": m.get("fix", ""), "confidence": m["confidence"]}
                for m in verified_sources
            ],
            "unverified": [
                {"context": m["context"][:100], "fix": m.get("fix", ""), "confidence": m["confidence"]}
                for m in unverified_sources[:2]
            ],
        },
        "fresh_reasoning": fresh_reasoning,
        "model_version": "deepseek-chat",
        "timestamp": datetime.now().isoformat(),
    }


# ── Write with Verification ───────────────────────────────────────

def write_verified(
    record_type: str,
    context: str,
    root_cause: str,
    fix: str = "",
    status: MemoryStatus = MemoryStatus.UNVERIFIED,
    model_version: str = "deepseek-chat",
    source_ids: list[int] = None,
    **kwargs,
) -> int:
    """Write a record with full verification metadata."""
    db = sqlite3.connect(str(BRAIN_DB))
    now = datetime.now().isoformat()

    cursor = db.execute("""
        INSERT INTO records (record_type, context, root_cause, fix, status, model_version,
            source_trace, created_at, reusability)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record_type, context, root_cause, fix,
        status.value, model_version,
        json.dumps(source_ids) if source_ids else "",
        now, kwargs.get("reusability", 0.5),
    ))
    record_id = cursor.lastrowid

    # Write lineage
    if source_ids:
        for pid in source_ids:
            db.execute("""
                INSERT INTO memory_lineage (child_id, parent_id, created_at)
                VALUES (?, ?, ?)
            """, (record_id, pid, now))

    db.commit()
    db.close()
    return record_id


# ── Lineage Query ──────────────────────────────────────────────────

def get_memory_lineage(record_id: int) -> list[dict]:
    """Trace where a memory came from — full provenance chain."""
    db = sqlite3.connect(str(BRAIN_DB))
    rows = db.execute("""
        SELECT r.id, r.record_type, r.context, r.status, r.created_at
        FROM memory_lineage ml
        JOIN records r ON r.id = ml.parent_id
        WHERE ml.child_id = ?
        ORDER BY ml.created_at
    """, (record_id,)).fetchall()
    db.close()
    return [{"id": r[0], "type": r[1], "context": r[2][:80], "status": r[3], "created": r[4]} for r in rows]
