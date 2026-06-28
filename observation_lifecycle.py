"""Observation Lifecycle — promote, archive, and deprecate observations.

From cheat-on-content: "Observations refuted by data get deleted;
observations absorbed into formal dimensions also get deleted.
It only holds what's most useful right now."

SECURITY GUARANTEES:
  - Weight changes are CAPPED at ±30% per adjustment
  - All weight changes have full audit trail in SQLite
  - Weights bounded to [0.1, 10.0] — can never go negative or explode
  - "Delete" = archive (soft delete), never hard delete
  - Promotion requires N successful uses (configurable, default 3)
  - Archival requires M consecutive failures OR N days unused

Lifecycle states:
  candidate  → new keyword/signal, not yet proven
  active     → proven useful, in production weighting
  stale      → hasn't been matched recently or performance declining
  archived   → preserved but no longer active (soft-deleted)
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum


class ObsState(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"


OBS_DB = Path("/opt/data/pi-intake/outreach/observations.db")

# Safety bounds
MAX_WEIGHT_CHANGE_PCT = 0.30   # Weight can't change more than 30% in one adjustment
MIN_WEIGHT = 0.1
MAX_WEIGHT = 10.0
PROMOTE_THRESHOLD = 3          # Number of successful uses needed to promote
STALE_FAILURE_THRESHOLD = 5    # Consecutive failures to mark stale
STALE_UNUSED_DAYS = 60         # Days unused before marking stale
ARCHIVE_AFTER_STALE_DAYS = 30  # Days in stale before archiving


def _get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(OBS_DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obs_key TEXT NOT NULL UNIQUE,     -- unique identifier (keyword, lead_source, template)
            obs_type TEXT NOT NULL,            -- keyword | lead_source | email_template | signal_rule
            state TEXT NOT NULL DEFAULT 'candidate',
            weight REAL DEFAULT 1.0,
            use_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            consecutive_failures INTEGER DEFAULT 0,
            last_used_at TEXT,
            last_success_at TEXT,
            created_at TEXT,
            promoted_at TEXT,
            archived_at TEXT,
            notes TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS weight_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obs_key TEXT NOT NULL,
            old_weight REAL,
            new_weight REAL,
            old_state TEXT,
            new_state TEXT,
            reason TEXT,
            changed_at TEXT
        )
    """)
    db.commit()
    return db


# ── Observation Registration ───────────────────────────────────────

def register_observation(obs_key: str, obs_type: str, initial_weight: float = 1.0, notes: str = ""):
    """Register a new observation (keyword, rule, template, etc.)."""
    db = _get_db()
    now = datetime.now().isoformat()

    weight = max(MIN_WEIGHT, min(MAX_WEIGHT, initial_weight))

    db.execute("""
        INSERT OR IGNORE INTO observations (obs_key, obs_type, state, weight, created_at, notes)
        VALUES (?, ?, 'candidate', ?, ?, ?)
    """, (obs_key, obs_type, weight, now, notes))
    db.commit()
    db.close()


def record_use(obs_key: str, success: bool):
    """Record that an observation was used, with success/failure."""
    db = _get_db()
    now = datetime.now().isoformat()

    row = db.execute(
        "SELECT state, use_count, success_count, consecutive_failures, weight FROM observations WHERE obs_key = ?",
        (obs_key,)
    ).fetchone()

    if not row:
        db.close()
        return

    state, use_count, success_count, consec_fails, weight = row
    new_use_count = use_count + 1
    new_success_count = success_count + (1 if success else 0)
    new_consec_fails = 0 if success else consec_fails + 1
    new_state = state

    # State transitions
    if state == ObsState.CANDIDATE and new_success_count >= PROMOTE_THRESHOLD:
        new_state = ObsState.ACTIVE
        db.execute("""
            INSERT INTO weight_changes (obs_key, old_weight, new_weight, old_state, new_state, reason, changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (obs_key, weight, weight, state, new_state, f"Promoted after {new_success_count} successful uses", now))

    elif state in (ObsState.ACTIVE, ObsState.STALE) and new_consec_fails >= STALE_FAILURE_THRESHOLD:
        new_state = ObsState.STALE

    # Update record
    db.execute("""
        UPDATE observations 
        SET use_count = ?, success_count = ?, consecutive_failures = ?,
            state = ?, last_used_at = ?,
            last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END
        WHERE obs_key = ?
    """, (new_use_count, new_success_count, new_consec_fails, new_state, now,
          success, now, obs_key))

    db.commit()
    db.close()


def adjust_weight(obs_key: str, new_weight: float, reason: str):
    """Adjust an observation's weight with safety bounds.

    SECURITY: Weight change is capped at ±30% per adjustment.
    Weight is always bounded to [0.1, 10.0].
    Full audit trail recorded.
    """
    db = _get_db()
    now = datetime.now().isoformat()

    row = db.execute(
        "SELECT weight, state FROM observations WHERE obs_key = ?",
        (obs_key,)
    ).fetchone()

    if not row:
        db.close()
        return False

    old_weight, state = row
    new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))

    # Cap the change
    max_change = old_weight * MAX_WEIGHT_CHANGE_PCT
    if abs(new_weight - old_weight) > max_change:
        if new_weight > old_weight:
            new_weight = old_weight + max_change
        else:
            new_weight = old_weight - max_change
        reason += f" (capped: ±{MAX_WEIGHT_CHANGE_PCT:.0%} limit)"

    db.execute("UPDATE observations SET weight = ? WHERE obs_key = ?", (new_weight, obs_key))
    db.execute("""
        INSERT INTO weight_changes (obs_key, old_weight, new_weight, old_state, new_state, reason, changed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (obs_key, old_weight, new_weight, state, state, reason, now))
    db.commit()
    db.close()
    return True


def run_archive_cycle():
    """Run the archive cycle: mark stale → archive after grace period.

    Should be called periodically (weekly).
    """
    db = _get_db()
    now = datetime.now().isoformat()

    # Mark unused observations as stale
    cutoff = (datetime.now() - timedelta(days=STALE_UNUSED_DAYS)).isoformat()
    db.execute("""
        UPDATE observations 
        SET state = 'stale'
        WHERE state = 'active' 
          AND (last_used_at IS NULL OR last_used_at < ?)
    """, (cutoff,))

    # Archive stale observations after grace period
    archive_cutoff = (datetime.now() - timedelta(days=ARCHIVE_AFTER_STALE_DAYS)).isoformat()
    stale_count = db.execute("""
        SELECT COUNT(*) FROM observations 
        WHERE state = 'stale' AND last_used_at < ?
    """, (archive_cutoff,)).fetchone()[0]

    db.execute("""
        UPDATE observations 
        SET state = 'archived', archived_at = ?
        WHERE state = 'stale' AND last_used_at < ?
    """, (now, archive_cutoff))

    # Log the archive changes
    for row in db.execute(
        "SELECT obs_key, weight FROM observations WHERE state = 'archived' AND archived_at = ?", (now,)
    ).fetchall():
        db.execute("""
            INSERT INTO weight_changes (obs_key, old_weight, new_weight, old_state, new_state, reason, changed_at)
            VALUES (?, ?, ?, 'stale', 'archived', 'Auto-archived after stale grace period', ?)
        """, (row[0], row[1], 0.0, now))

    db.commit()
    db.close()
    return {"newly_archived": stale_count}


def get_active_observations(obs_type: str = None) -> list[dict]:
    """Get all active (non-archived) observations, optionally filtered by type."""
    db = _get_db()
    if obs_type:
        rows = db.execute(
            "SELECT obs_key, obs_type, state, weight, use_count, success_count, consecutive_failures FROM observations WHERE state != 'archived' AND obs_type = ? ORDER BY weight DESC",
            (obs_type,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT obs_key, obs_type, state, weight, use_count, success_count, consecutive_failures FROM observations WHERE state != 'archived' ORDER BY weight DESC"
        ).fetchall()

    db.close()
    return [
        {
            "key": r[0], "type": r[1], "state": r[2], "weight": r[3],
            "use_count": r[4], "success_count": r[5], "consecutive_failures": r[6],
            "success_rate": round(r[5] / max(r[4], 1), 2),
        }
        for r in rows
    ]


def get_observation_history(obs_key: str) -> list[dict]:
    """Get the full weight change history for an observation."""
    db = _get_db()
    rows = db.execute(
        "SELECT old_weight, new_weight, old_state, new_state, reason, changed_at FROM weight_changes WHERE obs_key = ? ORDER BY changed_at",
        (obs_key,)
    ).fetchall()
    db.close()
    return [
        {"old_weight": r[0], "new_weight": r[1], "old_state": r[2], "new_state": r[3], "reason": r[4], "changed_at": r[5]}
        for r in rows
    ]


# ── Convenience: Seed pipeline observations ────────────────────────

def seed_pipeline_observations():
    """Register all current pipeline keywords and rules as observations."""
    from outreach.signal_engine import HIGH_INTENT_KEYWORDS, MEDIUM_INTENT_KEYWORDS

    for kw in HIGH_INTENT_KEYWORDS:
        register_observation(kw, "keyword", initial_weight=2.0, notes="High-intent signal keyword")

    for kw in MEDIUM_INTENT_KEYWORDS:
        register_observation(kw, "keyword", initial_weight=1.0, notes="Medium-intent signal keyword")

    # Register email templates
    register_observation("email_diagnostic_report", "email_template", initial_weight=1.0, notes="Day 1 diagnostic report email")
    register_observation("email_followup_1", "email_template", initial_weight=1.0, notes="Day 3 follow-up email")
    register_observation("email_followup_2", "email_template", initial_weight=1.0, notes="Day 7 follow-up email")
    register_observation("email_demo_invite", "email_template", initial_weight=1.0, notes="Post-engagement demo invite")

    # Register signal rules
    register_observation("rule_high_intent_threshold", "signal_rule", initial_weight=1.0, notes="Min keywords for high-intent classification")
    register_observation("rule_medium_intent_threshold", "signal_rule", initial_weight=1.0, notes="Min keywords for medium-intent classification")


# Seed on import
seed_pipeline_observations()
