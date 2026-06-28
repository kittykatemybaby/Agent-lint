"""Blind Prediction + Retro Dataset.

From cheat-on-content: "Score → Blind-Predict → Publish → T+3d Retro → Evolve Rubric.
Every piece you don't retro is silently eroding your ability to see yourself."

For our outreach pipeline:
  Before action → Blind-Predict outcome (locked in prediction file)
  T+7d → Retro: compare actual vs predicted
  After 3 same-direction misses → auto-adjust signal keyword weights

Dataset: SQLite with prediction → actual pairs.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional


PREDICT_DB = Path("/opt/data/pi-intake/outreach/predictions.db")


def _get_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(PREDICT_DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            firm_name TEXT,
            action_type TEXT NOT NULL,       -- diagnostic_email | followup_1 | followup_2 | demo_invite
            predicted_outcome TEXT NOT NULL,  -- opened | replied | ignored | bounced
            predicted_confidence REAL,        -- 0-1
            predicted_at TEXT NOT NULL,
            retro_due_at TEXT NOT NULL,       -- when to check back
            actual_outcome TEXT,              -- filled in at retro time
            actual_at TEXT,
            prediction_correct INTEGER,       -- 1/0/NULL (not yet retro'd)
            weights_adjusted INTEGER DEFAULT 0, -- was keyword weighting changed based on this?
            notes TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS weight_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            old_weight REAL,
            new_weight REAL,
            reason TEXT,
            adjusted_at TEXT
        )
    """)
    db.commit()
    return db


# ── Prediction Recording ───────────────────────────────────────────

def record_prediction(
    lead_id: str,
    firm_name: str,
    action_type: str,
    predicted_outcome: str,
    predicted_confidence: float,
) -> int:
    """Record a blind prediction BEFORE taking action.

    This must be called before the outreach email is sent.
    The prediction is locked — cannot be changed after recording.
    """
    db = _get_db()
    now = datetime.now().isoformat()
    retro_due = (datetime.now() + timedelta(days=7)).isoformat()

    cursor = db.execute("""
        INSERT INTO predictions (lead_id, firm_name, action_type, predicted_outcome,
            predicted_confidence, predicted_at, retro_due_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (lead_id, firm_name, action_type, predicted_outcome, predicted_confidence, now, retro_due))
    db.commit()
    pred_id = cursor.lastrowid
    db.close()
    return pred_id


# ── Retro: Compare Prediction vs Actual ────────────────────────────

def retro_prediction(prediction_id: int, actual_outcome: str):
    """Record the actual outcome of a prediction. Compare with predicted."""
    db = _get_db()
    now = datetime.now().isoformat()

    row = db.execute(
        "SELECT predicted_outcome, lead_id, firm_name FROM predictions WHERE id = ?",
        (prediction_id,)
    ).fetchone()

    if not row:
        db.close()
        return

    predicted = row[0]
    correct = 1 if actual_outcome == predicted else 0

    db.execute("""
        UPDATE predictions 
        SET actual_outcome = ?, actual_at = ?, prediction_correct = ?
        WHERE id = ?
    """, (actual_outcome, now, correct, prediction_id))
    db.commit()
    db.close()


def retro_all_due() -> list[dict]:
    """Find all predictions that are due for retro but haven't been retro'd yet.
    
    Returns list of predictions that need human (or agent) to fill in actual_outcome.
    """
    db = _get_db()
    now = datetime.now().isoformat()

    rows = db.execute("""
        SELECT id, lead_id, firm_name, action_type, predicted_outcome, predicted_confidence,
               predicted_at, retro_due_at
        FROM predictions
        WHERE actual_outcome IS NULL AND retro_due_at <= ?
        ORDER BY retro_due_at ASC
    """, (now,)).fetchall()
    db.close()

    return [
        {
            "id": r[0],
            "lead_id": r[1],
            "firm_name": r[2],
            "action_type": r[3],
            "predicted": r[4],
            "confidence": r[5],
            "predicted_at": r[6],
            "retro_due": r[7],
        }
        for r in rows
    ]


# ── Accuracy Analysis ──────────────────────────────────────────────

def prediction_accuracy(days: int = 30) -> dict:
    """Calculate prediction accuracy over the last N days."""
    db = _get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    total = db.execute(
        "SELECT COUNT(*) FROM predictions WHERE actual_outcome IS NOT NULL AND predicted_at >= ?",
        (cutoff,)
    ).fetchone()[0]

    if total == 0:
        db.close()
        return {"total_predictions": 0, "accuracy": None, "by_action": {}, "by_outcome": {}}

    correct = db.execute(
        "SELECT COUNT(*) FROM predictions WHERE prediction_correct = 1 AND predicted_at >= ?",
        (cutoff,)
    ).fetchone()[0]

    # By action type
    by_action = {}
    for row in db.execute(
        "SELECT action_type, COUNT(*), SUM(prediction_correct) FROM predictions WHERE actual_outcome IS NOT NULL AND predicted_at >= ? GROUP BY action_type",
        (cutoff,)
    ).fetchall():
        by_action[row[0]] = {
            "total": row[1],
            "correct": row[2] or 0,
            "accuracy": round((row[2] or 0) / row[1], 2) if row[1] > 0 else 0,
        }

    # By predicted outcome
    by_outcome = {}
    for row in db.execute(
        "SELECT predicted_outcome, COUNT(*), SUM(prediction_correct) FROM predictions WHERE actual_outcome IS NOT NULL AND predicted_at >= ? GROUP BY predicted_outcome",
        (cutoff,)
    ).fetchall():
        by_outcome[row[0]] = {
            "total": row[1],
            "correct": row[2] or 0,
            "accuracy": round((row[2] or 0) / row[1], 2) if row[1] > 0 else 0,
        }

    db.close()
    return {
        "total_predictions": total,
        "accuracy": round(correct / total, 2),
        "by_action": by_action,
        "by_outcome": by_outcome,
    }


# ── Weight Evolution ───────────────────────────────────────────────

def check_need_weight_adjustment() -> list[dict]:
    """Check if any keyword weights need adjustment.

    Rule: 3 same-direction misses in a row for the same action type
    → flag for weight adjustment.
    """
    db = _get_db()

    adjustments = []
    for action_type in ["diagnostic_email", "followup_1", "followup_2", "demo_invite"]:
        rows = db.execute("""
            SELECT predicted_outcome, prediction_correct 
            FROM predictions 
            WHERE action_type = ? AND actual_outcome IS NOT NULL
            ORDER BY actual_at DESC LIMIT 10
        """, (action_type,)).fetchall()

        # Check for 3 consecutive misses
        if len(rows) >= 3:
            last_3 = [r[1] for r in rows[:3]]
            if all(c == 0 for c in last_3):
                adjustments.append({
                    "action_type": action_type,
                    "last_3_predictions": [r[0] for r in rows[:3]],
                    "all_missed": True,
                    "suggestion": f"Consider adjusting outreach strategy for {action_type}",
                })

    db.close()
    return adjustments


def record_weight_adjustment(keyword: str, old_weight: float, new_weight: float, reason: str):
    """Record a keyword weight change for audit trail."""
    db = _get_db()
    db.execute("""
        INSERT INTO weight_history (keyword, old_weight, new_weight, reason, adjusted_at)
        VALUES (?, ?, ?, ?, ?)
    """, (keyword, old_weight, new_weight, reason, datetime.now().isoformat()))
    db.commit()
    db.close()


# ── Prediction Helper ──────────────────────────────────────────────

def predict_for_lead(lead: dict, action_type: str) -> dict:
    """Make a blind prediction for a lead before outreach.

    Uses simple heuristics (not LLM — kept deterministic for reproducibility).
    Returns (predicted_outcome, confidence).
    """
    intent = lead.get("intent_level", "low")
    keywords = lead.get("matched_keywords", [])
    num_keywords = len(keywords)
    has_email = bool(lead.get("email", ""))

    if action_type == "diagnostic_email":
        if intent == "high" and num_keywords >= 3:
            return {"outcome": "replied", "confidence": 0.6}
        elif intent == "high":
            return {"outcome": "opened", "confidence": 0.7}
        else:
            return {"outcome": "ignored", "confidence": 0.8}

    elif action_type == "followup_1":
        return {"outcome": "ignored", "confidence": 0.9}  # Most followups get ignored

    elif action_type == "followup_2":
        return {"outcome": "replied", "confidence": 0.5}  # "One question" email has higher reply rate

    elif action_type == "demo_invite":
        return {"outcome": "opened", "confidence": 0.6}

    return {"outcome": "ignored", "confidence": 0.5}
