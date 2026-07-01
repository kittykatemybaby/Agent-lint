"""Signal Correlation Engine — cross-layer trend confirmation.

A single signal in one layer = noise.
Same signal in 3+ layers = confirmed trend.
Developer demand + capital flow + indie revenue = act now.
"""

import json, sqlite3, re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

CORRELATION_DB = Path(__file__).parent / "signal_correlations.db"


def _db():
    db = sqlite3.connect(str(CORRELATION_DB))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS raw_signals (
        id INTEGER PRIMARY KEY, layer TEXT, source TEXT,
        keywords TEXT, description TEXT, signal_strength REAL,
        captured_at TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS confirmed_trends (
        id INTEGER PRIMARY KEY, trend_name TEXT, confirmed_layers TEXT,
        total_strength REAL, first_seen TEXT, last_seen TEXT
    )""")
    return db


# ── Layer Definitions ─────────────────────────────────────────────

LAYERS = {
    "developer": {
        "weight": 0.25,  # frontier signal — what's next
        "sources": ["github_star_velocity", "npm_downloads", "hn_ask", "stackoverflow_velocity",
                     "reddit_r_programming", "arxiv_preprints", "producthunt"],
        "meaning": "Developers are building/adopting — early trend signal"
    },
    "capital": {
        "weight": 0.30,  # money follows conviction
        "sources": ["techcrunch_funding", "crunchbase", "sec_filings", "yc_jobs",
                     "vc_portfolio", "angelist_syndicates"],
        "meaning": "Capital is flowing — institutional conviction"
    },
    "money_flow": {
        "weight": 0.25,  # people actually paying NOW
        "sources": ["flippa", "microacquire", "gumroad", "appsumo", "upwork_jobs",
                     "patreon_categories", "substack_top"],
        "meaning": "People are paying right now — proven demand"
    },
    "pain": {
        "weight": 0.15,  # dissatisfaction creates switching opportunity
        "sources": ["g2_reviews", "capterra_reviews", "reddit_switching",
                     "hn_alternatives", "twitter_complaints"],
        "meaning": "Users are unhappy with existing solutions"
    },
    "regulation": {
        "weight": 0.05,  # compliance creates forced demand
        "sources": ["gov_contracts", "eu_ai_act", "sec_enforcement",
                     "osha_violations", "ftc_complaints"],
        "meaning": "Regulation is creating mandatory demand"
    },
}


# ── Record Signals ────────────────────────────────────────────────

def record_signal(layer: str, source: str, keywords: str, description: str,
                  signal_strength: float = 0.5):
    db = _db()
    db.execute("""INSERT INTO raw_signals (layer, source, keywords, description, signal_strength, captured_at)
        VALUES (?,?,?,?,?,?)""",
        (layer, source, keywords, description, signal_strength, datetime.now().isoformat()))
    db.commit(); db.close()


# ── Cross-Layer Correlation ───────────────────────────────────────

def _extract_topics(text: str) -> set[str]:
    """Extract normalized topic keywords from text."""
    # Remove common noise words
    noise = {"the","a","an","is","are","for","with","and","or","this","that","from","has","been","will","can"}
    words = set(re.findall(r'\w{4,}', text.lower()))
    return words - noise


def correlate_signals(time_window_hours: int = 168) -> list[dict]:
    """Find signals that appear across multiple layers within the time window.

    Returns confirmed trends sorted by total_strength (layer_weight × signal_strength).
    """
    db = _db()
    cutoff = (datetime.now() - __import__('datetime').timedelta(hours=time_window_hours)).isoformat()

    rows = db.execute("""SELECT id, layer, keywords, description, signal_strength, captured_at
        FROM raw_signals WHERE captured_at >= ? ORDER BY captured_at DESC""",
        (cutoff,)).fetchall()
    db.close()

    if not rows:
        return []

    # Group signals by topic clusters
    topic_to_signals: dict[str, list] = defaultdict(list)
    for r in rows:
        keywords = r[2] or ""
        topics = _extract_topics(keywords + " " + (r[3] or ""))
        for t in topics:
            topic_to_signals[t].append({
                "id": r[0], "layer": r[1], "keywords": keywords,
                "description": r[3], "signal_strength": r[4], "captured_at": r[5],
                "topic": t,
            })

    # Find topics confirmed across 3+ layers. Merge co-occurring keywords.
    merged = {}
    for topic, signals in topic_to_signals.items():
        if len(signals) >= 2:
            found = False
            for existing in list(merged.keys()):
                if topic in existing or existing in topic:
                    merged[existing].extend(signals)
                    found = True
                    break
            if not found:
                merged[topic] = list(signals)

    confirmed = []
    for topic, signals in merged.items():
            layers_hit = set(s["layer"] for s in signals)
            total_strength = sum(
                s["signal_strength"] * LAYERS.get(s["layer"], {}).get("weight", 0.2)
                for s in signals
            )
            confirmed.append({
                "trend": topic,
                "layers": sorted(layers_hit),
                "layer_count": len(layers_hit),
                "total_strength": round(total_strength, 3),
                "signals": signals[:5],
                "interpretation": " + ".join(
                    LAYERS.get(l, {}).get("meaning", l) for l in layers_hit
                ),
            })

    return sorted(confirmed, key=lambda c: -c["total_strength"])


# ── Trend Interpretation ──────────────────────────────────────────

def interpret_trend(trend: dict) -> str:
    """Human-readable interpretation of a confirmed trend."""
    layers = trend["layers"]
    if "developer" in layers and "capital" in layers and "money_flow" in layers:
        return "🔥 Full-stack confirmation: developers want it, investors bet on it, people pay for it. Act now."
    elif "developer" in layers and "money_flow" in layers:
        return "📈 Demand-led: developers are building AND people are paying. Missing institutional money — early stage."
    elif "capital" in layers and "regulation" in layers:
        return "🏛 Compliance-driven: investors see regulatory tailwind. Watch for developer adoption to confirm."
    elif "pain" in layers and "money_flow" in layers:
        return "💰 Migration opportunity: people are unhappy AND willing to pay for alternatives."
    elif len(layers) >= 3:
        return f"📊 Multi-layer signal ({len(layers)} layers). Investigate further."
    else:
        return "🔍 Emerging signal. Monitor for additional layer confirmation."


# ── Query Builder (for Opportunity Scan) ──────────────────────────

def top_confirmed_trends(hours: int = 168, min_layers: int = 2) -> list[dict]:
    """Get actionable trends for the opportunity scan."""
    trends = correlate_signals(hours)
    return [
        {**t, "interpretation": interpret_trend(t)}
        for t in trends
        if t["layer_count"] >= min_layers
    ]
