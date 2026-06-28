"""Error Gene Map — lightweight self-healing error knowledge base.

From Helix: "The fix is stored in the Gene Map — a SQLite knowledge base.
Next time the same error hits, it's fixed in under 1ms. No LLM call."

Database schema:
  gene_map:
    error_pattern TEXT PRIMARY KEY  — normalized error signature
    fix_type TEXT                    — retry | backoff | alternate | skip | escalate
    fix_params TEXT (JSON)           — parameters for the fix (delay, alt endpoint, etc.)
    fix_count INTEGER                — how many times this fix was used
    success_count INTEGER            — how many times it worked
    last_seen TEXT                   — ISO timestamp
    created_at TEXT
"""

import json
import sqlite3
import hashlib
import time
import re
from datetime import datetime
from pathlib import Path
from enum import Enum


class FixType(str, Enum):
    RETRY = "retry"           # Retry with backoff
    BACKOFF = "backoff"       # Wait and retry
    ALTERNATE = "alternate"   # Use fallback endpoint/method
    SKIP = "skip"             # Skip this item, continue
    ESCALATE = "escalate"     # Must escalate to human
    IGNORE = "ignore"         # Known benign, ignore


GENE_DB = Path("/opt/data/pi-intake/outreach/gene_map.db")


def _get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(GENE_DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS gene_map (
            error_pattern TEXT PRIMARY KEY,
            fix_type TEXT NOT NULL,
            fix_params TEXT DEFAULT '{}',
            fix_count INTEGER DEFAULT 1,
            success_count INTEGER DEFAULT 1,
            last_seen TEXT,
            created_at TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_pattern TEXT,
            error_raw TEXT,
            context TEXT,
            fix_applied TEXT,
            fix_success INTEGER,
            timestamp TEXT
        )
    """)
    db.commit()
    return db


def _normalize_error(error_msg: str) -> str:
    """Normalize an error message into a stable pattern by removing
    variable parts (URLs, IDs, timestamps, numbers)."""
    # Remove HTTP status codes with URLs
    pattern = re.sub(r'https?://\S+', '<URL>', error_msg)
    # Remove numeric IDs
    pattern = re.sub(r'\b[0-9a-f]{8,}\b', '<ID>', pattern)
    # Remove timestamps
    pattern = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', '<TS>', pattern)
    # Remove IPs
    pattern = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<IP>', pattern)
    # Collapse whitespace
    pattern = re.sub(r'\s+', ' ', pattern).strip()
    # Truncate long patterns
    if len(pattern) > 200:
        pattern = pattern[:200]
    return pattern


# ── Known Error Patterns (pre-seeded from our own experience) ──────

KNOWN_ERRORS = [
    {
        "pattern": "DeepSeek API timeout",
        "fix_type": FixType.RETRY,
        "fix_params": {"delay": 3, "max_retries": 2},
    },
    {
        "pattern": "DeepSeek API 5xx",
        "fix_type": FixType.BACKOFF,
        "fix_params": {"delay": 5, "max_retries": 2, "backoff_factor": 2},
    },
    {
        "pattern": "Reddit API rate limit 429",
        "fix_type": FixType.BACKOFF,
        "fix_params": {"delay": 60, "max_retries": 1},
    },
    {
        "pattern": "Edge TTS generation failed",
        "fix_type": FixType.ALTERNATE,
        "fix_params": {"fallback_voice": "en-US-JennyNeural"},
    },
    {
        "pattern": "Edge TTS file empty",
        "fix_type": FixType.ALTERNATE,
        "fix_params": {"fallback": "twilio_say"},
    },
    {
        "pattern": "localhost.run tunnel dropped 502",
        "fix_type": FixType.RETRY,
        "fix_params": {"delay": 10, "max_retries": 2},
    },
    {
        "pattern": "Twilio Gather returned empty speech_result",
        "fix_type": FixType.RETRY,
        "fix_params": {"delay": 2, "max_retries": 1},
    },
    {
        "pattern": "himalaya send returned non-zero",
        "fix_type": FixType.RETRY,
        "fix_params": {"delay": 5, "max_retries": 1},
    },
    {
        "pattern": "GitHub API rate limit 403",
        "fix_type": FixType.BACKOFF,
        "fix_params": {"delay": 300, "max_retries": 1},
    },
    {
        "pattern": "Contact enrichment confidence low",
        "fix_type": FixType.SKIP,
        "fix_params": {"reason": "lead has no discoverable email"},
    },
]


def seed_known_errors():
    """Seed the gene map with our known error patterns."""
    db = _get_db()
    now = datetime.now().isoformat()
    for entry in KNOWN_ERRORS:
        db.execute("""
            INSERT OR IGNORE INTO gene_map (error_pattern, fix_type, fix_params, last_seen, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            entry["pattern"],
            entry["fix_type"].value,
            json.dumps(entry["fix_params"]),
            now, now,
        ))
    db.commit()
    db.close()


def lookup_fix(error_msg: str) -> dict | None:
    """Look up a known fix for an error. Returns None if no known fix."""
    pattern = _normalize_error(error_msg)
    db = _get_db()

    # Exact match first
    row = db.execute(
        "SELECT fix_type, fix_params, fix_count, success_count FROM gene_map WHERE error_pattern = ?",
        (pattern,)
    ).fetchone()

    if not row:
        # Fuzzy: try partial match
        row = db.execute(
            "SELECT fix_type, fix_params, fix_count, success_count FROM gene_map WHERE ? LIKE '%' || error_pattern || '%' LIMIT 1",
            (error_msg[:200],)
        ).fetchone()

    db.close()

    if row:
        return {
            "fix_type": row[0],
            "fix_params": json.loads(row[1]),
            "fix_count": row[2],
            "success_count": row[3],
            "confidence": row[3] / max(row[2], 1),
        }
    return None


def record_fix(error_msg: str, fix_type: FixType, fix_params: dict, success: bool):
    """Record a fix attempt — success or failure."""
    pattern = _normalize_error(error_msg)
    db = _get_db()
    now = datetime.now().isoformat()

    # Upsert gene_map
    existing = db.execute(
        "SELECT fix_count, success_count FROM gene_map WHERE error_pattern = ?",
        (pattern,)
    ).fetchone()

    if existing:
        db.execute("""
            UPDATE gene_map 
            SET fix_count = fix_count + 1,
                success_count = success_count + ?,
                last_seen = ?
            WHERE error_pattern = ?
        """, (1 if success else 0, now, pattern))
    else:
        db.execute("""
            INSERT INTO gene_map (error_pattern, fix_type, fix_params, fix_count, success_count, last_seen, created_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
        """, (pattern, fix_type.value, json.dumps(fix_params), 1 if success else 0, now, now))

    # Log to error_log
    db.execute("""
        INSERT INTO error_log (error_pattern, error_raw, fix_applied, fix_success, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (pattern, error_msg[:500], fix_type.value, 1 if success else 0, now))

    db.commit()
    db.close()


def apply_fix(error_msg: str, context: str = "") -> dict:
    """Look up and apply a fix for an error. Returns action to take."""
    fix = lookup_fix(error_msg)

    if fix and fix["confidence"] >= 0.5:
        return {
            "known": True,
            "action": fix["fix_type"],
            "params": fix["fix_params"],
            "confidence": fix["confidence"],
        }

    # Unknown error — escalate for diagnosis
    return {
        "known": False,
        "action": FixType.ESCALATE,
        "params": {"reason": "unknown_error", "error": error_msg[:200]},
        "confidence": 0.0,
    }


def gene_map_stats() -> dict:
    """Get stats about the gene map."""
    db = _get_db()
    total = db.execute("SELECT COUNT(*) FROM gene_map").fetchone()[0]
    avg_confidence = db.execute(
        "SELECT AVG(CAST(success_count AS FLOAT) / MAX(fix_count, 1)) FROM gene_map"
    ).fetchone()[0] or 0.0
    total_fixes = db.execute("SELECT SUM(fix_count) FROM gene_map").fetchone()[0] or 0
    db.close()
    return {
        "patterns_stored": total,
        "avg_fix_confidence": round(avg_confidence, 2),
        "total_fix_attempts": total_fixes,
    }


# Seed on import
seed_known_errors()
