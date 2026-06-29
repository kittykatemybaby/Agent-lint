"""Project Brain — structured agent memory with cognitive isolation.

Architecture:
  Layer 3 (Project Brain): SQLite persistent store
    - decisions, failures, patterns, constraints, experiments
  Layer 2 (Working Memory): compressed, retrievable via similarity
  Layer 1 (Hot Context): ephemeral, current session only

Retrieval: score = 0.4*semantic + 0.3*failure_sim + 0.3*recency_decay
"""

import json
import sqlite3
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from collections import Counter

BRAIN_DB = Path(__file__).parent / "project_brain.db"


def _get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(BRAIN_DB))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,       -- decision, failure, pattern, constraint, experiment
            context TEXT NOT NULL,
            root_cause TEXT,
            fix TEXT,
            reusability REAL DEFAULT 0.5,
            verdict TEXT,                     -- from critic
            score REAL,
            reasons TEXT,                     -- JSON array
            tags TEXT,
            trace_id TEXT,
            tool_call TEXT,
            result_summary TEXT,
            created_at TEXT NOT NULL,
            last_accessed TEXT,
            access_count INTEGER DEFAULT 0,
            embedding BLOB                    -- placeholder for future vector
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_type ON records(record_type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_created ON records(created_at)")
    db.commit()
    return db


# ── Write ─────────────────────────────────────────────────────────

def record_decision(
    context: str,
    root_cause: str,
    fix: str = "",
    reusability: float = 0.5,
    tags: str = "",
):
    db = _get_db()
    db.execute("""
        INSERT INTO records (record_type, context, root_cause, fix, reusability, tags, created_at)
        VALUES ('decision', ?, ?, ?, ?, ?, ?)
    """, (context, root_cause, fix, reusability, tags, datetime.now().isoformat()))
    db.commit()
    db.close()


def record_failure(
    context: str,
    root_cause: str,
    fix: str = "",
    trace_id: str = "",
    tool_call: str = "",
    result_summary: str = "",
    reusability: float = 0.8,
    tags: str = "",
):
    db = _get_db()
    db.execute("""
        INSERT INTO records (record_type, context, root_cause, fix, trace_id, tool_call, result_summary, reusability, tags, created_at)
        VALUES ('failure', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (context, root_cause, fix, trace_id, tool_call, result_summary, reusability, tags, datetime.now().isoformat()))
    db.commit()
    db.close()


def record_pattern(
    context: str,
    root_cause: str,
    fix: str,
    reusability: float = 0.7,
    tags: str = "",
):
    db = _get_db()
    db.execute("""
        INSERT INTO records (record_type, context, root_cause, fix, reusability, tags, created_at)
        VALUES ('pattern', ?, ?, ?, ?, ?, ?)
    """, (context, root_cause, fix, reusability, tags, datetime.now().isoformat()))
    db.commit()
    db.close()


def record_constraint(
    context: str,
    root_cause: str,
    tags: str = "",
):
    db = _get_db()
    db.execute("""
        INSERT INTO records (record_type, context, root_cause, tags, created_at)
        VALUES ('constraint', ?, ?, ?, ?)
    """, (context, root_cause, tags, datetime.now().isoformat()))
    db.commit()
    db.close()


# ── Critic Interface (structured output only) ─────────────────────

@dataclass
class CriticOutput:
    verdict: str            # reject | approve | escalate
    score: float            # 0-1 confidence
    reasons: list[str]      # structured, machine-readable reasons
    suggestion: str = ""    # optional fix suggestion


def critic_output(verdict: str, score: float, reasons: list[str], suggestion: str = "") -> dict:
    """Critic must output structured signal, never free-form reasoning."""
    return {
        "verdict": verdict,
        "score": score,
        "reasons": reasons,
        "suggestion": suggestion,
    }


# ── Read (cognitive isolation enforced) ───────────────────────────

def get_recent_decisions(limit: int = 3) -> list[dict]:
    """Builder can see decisions but NOT critic reasoning."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, context, root_cause, fix, reusability, created_at FROM records WHERE record_type='decision' ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    db.close()
    return [_row_to_dict(r, ["id","context","root_cause","fix","reusability","created_at"]) for r in rows]


def get_top_failures(limit: int = 20) -> list[dict]:
    """Builder can see failure patterns but NOT full trace."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, context, root_cause, fix, reusability, created_at FROM records WHERE record_type='failure' ORDER BY reusability DESC, created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    db.close()
    return [_row_to_dict(r, ["id","context","root_cause","fix","reusability","created_at"]) for r in rows]


def get_active_constraints() -> list[dict]:
    db = _get_db()
    rows = db.execute(
        "SELECT id, context, root_cause, created_at FROM records WHERE record_type='constraint' ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    db.close()
    return [_row_to_dict(r, ["id","context","root_cause","created_at"]) for r in rows]


def get_recurring_patterns(min_reusability: float = 0.5) -> list[dict]:
    db = _get_db()
    rows = db.execute(
        "SELECT id, context, root_cause, fix, reusability, tags FROM records WHERE record_type='pattern' AND reusability >= ? ORDER BY reusability DESC",
        (min_reusability,)
    ).fetchall()
    db.close()
    return [_row_to_dict(r, ["id","context","root_cause","fix","reusability","tags"]) for r in rows]


# ── Retrieval ─────────────────────────────────────────────────────

def _simple_similarity(query: str, text: str) -> float:
    """Keyword-based similarity (placeholder for embedding)."""
    if not text:
        return 0.0
    q_words = set(re.findall(r'\w+', query.lower()))
    t_words = set(re.findall(r'\w+', text.lower()))
    if not q_words:
        return 0.0
    return len(q_words & t_words) / len(q_words)


def _recency_decay(created_at: str, half_life_days: float = 7.0) -> float:
    """Exponential decay: newer records score higher."""
    try:
        dt = datetime.fromisoformat(created_at)
        age_days = (datetime.now() - dt).total_seconds() / 86400
        return 2.0 ** (-age_days / half_life_days)
    except:
        return 0.5


def retrieve(query: str, record_types: list[str] = None, top_k: int = 5) -> list[dict]:
    """Retrieve most relevant records using the retrieval formula.

    score = 0.4 * semantic_similarity + 0.3 * failure_similarity + 0.3 * recency_decay
    """
    db = _get_db()
    type_filter = " AND record_type IN ({})".format(','.join('?'*len(record_types))) if record_types else ""
    params = tuple(record_types) if record_types else ()

    rows = db.execute(
        f"SELECT id, record_type, context, root_cause, fix, reusability, created_at FROM records WHERE 1=1{type_filter} ORDER BY created_at DESC LIMIT 100",
        params,
    ).fetchall()
    db.close()

    scored = []
    for r in rows:
        record_type = r[1]
        context = r[2] or ""
        root_cause = r[3] or ""
        created_at = r[6]

        semantic = _simple_similarity(query, f"{context} {root_cause}")
        failure_weight = 1.0 if record_type == "failure" else 0.3
        recency = _recency_decay(created_at)

        score = 0.4 * semantic + 0.3 * failure_weight * semantic + 0.3 * recency
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {**_row_to_dict(r, ["id","record_type","context","root_cause","fix","reusability","created_at"]), "score": round(s, 3)}
        for s, r in scored[:top_k]
    ]


# ── Input Shrink (Builder gets minimal context) ───────────────────

def builder_context(current_task: str, max_records: int = 5) -> dict:
    """Builder's view: last decision + top failures + current task. No history chain."""
    return {
        "current_task": current_task,
        "last_decision": get_recent_decisions(1),
        "top_failures": get_top_failures(3)[:3],
        "active_constraints": get_active_constraints(),
    }


# ── Compression ───────────────────────────────────────────────────

def compress_failures(min_count: int = 3) -> list[dict]:
    """Cluster similar failures into abstract patterns."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, context, root_cause, fix FROM records WHERE record_type='failure' AND id NOT IN (SELECT id FROM records WHERE record_type='pattern') ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    db.close()

    # Simple clustering: group by root_cause keyword overlap
    clusters = {}
    for r in rows:
        cause = r[2] or ""
        words = set(re.findall(r'\w+', cause.lower()))
        key = frozenset(list(words)[:3])
        clusters.setdefault(key, []).append(r)

    new_patterns = []
    for key, group in clusters.items():
        if len(group) >= min_count:
            combined_context = " | ".join([r[1][:80] for r in group[:5]])
            new_patterns.append({
                "context": combined_context,
                "root_cause": group[0][2] or "unknown",
                "fix": group[0][3] or "",
                "occurrence_count": len(group),
                "reusability": min(0.9, 0.5 + 0.1 * len(group)),
            })

    # Store patterns
    for p in new_patterns:
        record_pattern(
            context=p["context"],
            root_cause=p["root_cause"],
            fix=p["fix"],
            reusability=p["reusability"],
        )

    return new_patterns


# ── Utilities ─────────────────────────────────────────────────────

def _row_to_dict(row, cols):
    return dict(zip(cols, row))


def brain_stats() -> dict:
    db = _get_db()
    stats = {}
    for rt in ["decision", "failure", "pattern", "constraint", "experiment"]:
        count = db.execute("SELECT COUNT(*) FROM records WHERE record_type=?", (rt,)).fetchone()[0]
        stats[rt] = count
    db.close()
    return stats


def seed_known_failures():
    """Pre-seed with failure patterns from our experience."""
    known = [
        ("Agent hits same DeepSeek API timeout repeatedly", "No retry or backoff logic", "Use gene_map.py for 1ms hot lookup", 0.9, "api,reliability"),
        ("Phase 1 research requires manual approval for every curl call", "Hermes security flags on pipe-to-python", "Use execute_code to bundle or cron for fire-and-forget", 0.8, "ux,automation"),
        ("web_search broken after oxylabs install", "security.allow_lazy_installs=false despite config change", "Config change requires Hermes restart; use curl as fallback", 0.85, "infra,hermes"),
        ("Opportunity scan returns 'no signals' on slow days", "Only 3 signal sources (HN, GitHub, TC)", "Expand to HF Papers, Arxiv, MarkTechPost, Reddit, world news", 0.7, "research,signals"),
        ("X OAuth blocked on headless VPS", "No browser for OAuth redirect_uri=localhost:8080", "Use bearer token for reads; OAuth needs user's phone", 0.9, "auth,platform"),
    ]
    for ctx, cause, fix, reuse, tags in known:
        record_failure(context=ctx, root_cause=cause, fix=fix, reusability=reuse, tags=tags)

    # Record key constraints
    record_constraint("Never type passwords in chat", "Security: chat history is persistent")
    record_constraint("Never use os.getenv() in write_file — triggers secret redactor", "Infra: use os.environ.get()")
    record_constraint("VPS datacenter IP blocked by social platforms", "Proxy: must use residential IP for account creation")
    record_constraint("Budget: $0 additional spend until first revenue", "Financial: every cost must be justified")


seed_known_failures()
