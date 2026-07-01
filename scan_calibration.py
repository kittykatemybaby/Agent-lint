"""Scan Calibration Loop — prevents bias, gates complexity, feeds back validation.

Three mechanisms:
  1. Novelty Decay: penalize repeated signal patterns across runs
  2. Complexity Gate: auto-reject MVP > 2 components
  3. Product Feedback Loop: auto-correlate findings with existing module gaps
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import Counter

CALIBRATION_DB = Path(__file__).parent / "scan_calibration.db"


def _db():
    db = sqlite3.connect(str(CALIBRATION_DB))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS scan_history (
        id INTEGER PRIMARY KEY, run_at TEXT, category TEXT, keywords TEXT,
        src TEXT, complexity INTEGER
    )""")
    return db


# ── Mechanism 1: Novelty Decay ────────────────────────────────────

def novelty_score(idea_keywords: str, history_window: int = 10) -> float:
    """Score 0-1. 1 = completely novel. 0 = seen many times before."""
    db = _db()
    rows = db.execute(
        "SELECT keywords FROM scan_history ORDER BY run_at DESC LIMIT ?",
        (history_window,)
    ).fetchall()
    db.close()

    if not rows:
        return 1.0

    current_words = set(idea_keywords.lower().split())
    overlap_count = 0
    for (past_kw,) in rows:
        past_words = set(past_kw.lower().split())
        overlap = len(current_words & past_words) / max(len(current_words), 1)
        if overlap > 0.4:  # semantic threshold
            overlap_count += 1

    # Exponential decay: each overlapping past run halves the novelty
    return max(0.1, 0.5 ** overlap_count)


# ── Mechanism 2: Complexity Gate ──────────────────────────────────

def complexity_gate(estimated_components: int, max_components: int = 2) -> dict:
    """Reject ideas that require too many integrations."""
    if estimated_components > max_components:
        return {
            "verdict": "REJECT",
            "reason": f"Too many components ({estimated_components} > {max_components}). Split into smaller MVPs.",
            "suggestion": "What's the ONE most valuable integration? Ship that first."
        }
    return {"verdict": "APPROVE"}


# ── Mechanism 3: Product Feedback Loop ────────────────────────────

MODULE_GAP_MAP = {
    "observability": ["understand_agent", "trace", "debug", "explain"],
    "intercept": ["block", "safety", "guardrail", "prevent"],
    "cost": ["token", "cost", "budget", "optimize"],
    "replay": ["history", "audit", "replay", "record"],
}


def correlate_with_modules(idea_description: str) -> list[dict]:
    """Check if this idea matches gaps in our existing modules."""
    matches = []
    text = idea_description.lower()
    for module, keywords in MODULE_GAP_MAP.items():
        score = sum(1 for kw in keywords if kw in text) / len(keywords)
        if score > 0:
            matches.append({"module": module, "score": round(score, 2)})
    return sorted(matches, key=lambda m: -m["score"])


# ── Combined Gate (runs on every scan output) ─────────────────────

def scan_gate(idea: dict, run: bool = True) -> dict:
    """Must pass all three mechanisms before an opportunity is presented."""
    keywords = idea.get("keywords", idea.get("title", ""))
    complexity = idea.get("component_count", 1)

    # 1. Novelty check
    novelty = novelty_score(keywords)
    if novelty < 0.3:
        return {"verdict": "REJECT", "reasons": [f"Novelty too low ({novelty})"], "suggestion": "Rotate search queries"}

    # 2. Complexity check
    gate = complexity_gate(complexity)
    if gate["verdict"] == "REJECT":
        return {"verdict": "REJECT", "reasons": [gate["reason"]]}

    # 3. Product fit
    matches = correlate_with_modules(keywords)
    if matches:
        return {
            "verdict": "APPROVE",
            "novelty": round(novelty, 2),
            "module_matches": matches,
            "note": f"Validates: {', '.join(m['module'] for m in matches[:3])}"
        }

    return {"verdict": "APPROVE", "novelty": round(novelty, 2)}


# ── Record run ────────────────────────────────────────────────────

def record_scan(category: str, keywords: str, src: str, complexity: int):
    db = _db()
    db.execute("INSERT INTO scan_history (run_at, category, keywords, src, complexity) VALUES (?,?,?,?,?)",
               (datetime.now().isoformat(), category, keywords, src, complexity))
    db.commit()
    db.close()
