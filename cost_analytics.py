"""Cost Analytics — track and analyze AI agent token usage and costs.

Integrates with: DeepSeek API, gene_map (for error cost tracking),
research_audit (for per-action cost logging).

Outputs: cost-per-step, cost-per-task, cost trends, savings from gene_map.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field

COST_DB = Path(__file__).parent / "cost_analytics.db"

# DeepSeek pricing (per 1M tokens)
DEEPSEEK_PRICING = {
    "input": 0.27,      # $0.27 per 1M input tokens
    "output": 1.10,     # $1.10 per 1M output tokens
    "cached_input": 0.07,  # $0.07 per 1M cached input tokens
}


@dataclass
class CostEvent:
    timestamp: str
    agent: str
    task_id: str
    step: int
    event: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    gene_map_hit: bool = False  # $0 saved (1ms lookup instead of LLM)
    duration_ms: float = 0


def _get_db():
    db = sqlite3.connect(str(COST_DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS cost_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            agent TEXT,
            task_id TEXT,
            step INTEGER,
            event TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cached_tokens INTEGER DEFAULT 0,
            gene_map_hit INTEGER DEFAULT 0,
            duration_ms REAL DEFAULT 0
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_cost_task ON cost_events(task_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_cost_time ON cost_events(timestamp)")
    db.commit()
    return db


def _calc_cost(input_tokens: int, output_tokens: int, cached_tokens: int, gene_map_hit: bool) -> float:
    """Calculate cost in USD."""
    cost = 0.0
    if not gene_map_hit:
        cost += (input_tokens / 1_000_000) * DEEPSEEK_PRICING["input"]
        cost += (output_tokens / 1_000_000) * DEEPSEEK_PRICING["output"]
        cost += (cached_tokens / 1_000_000) * DEEPSEEK_PRICING["cached_input"]
    # gene_map hit = $0
    return round(cost, 6)


def record_cost(event: CostEvent):
    """Record a cost event."""
    db = _get_db()
    cost = _calc_cost(event.input_tokens, event.output_tokens,
                      event.cached_tokens, event.gene_map_hit)
    db.execute("""
        INSERT INTO cost_events (timestamp, agent, task_id, step, event,
            input_tokens, output_tokens, cached_tokens, gene_map_hit, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (event.timestamp, event.agent, event.task_id, event.step,
          event.event, event.input_tokens, event.output_tokens,
          event.cached_tokens, int(event.gene_map_hit), event.duration_ms))
    db.commit()
    db.close()
    return cost


def task_cost(task_id: str) -> dict:
    """Total cost for a specific task."""
    db = _get_db()
    rows = db.execute("""
        SELECT input_tokens, output_tokens, cached_tokens, gene_map_hit
        FROM cost_events WHERE task_id = ?
    """, (task_id,)).fetchall()

    total_input = sum(r[0] for r in rows)
    total_output = sum(r[1] for r in rows)
    total_cached = sum(r[2] for r in rows)
    gene_savings = sum(1 for r in rows if r[3])  # steps that cost $0

    cost = _calc_cost(total_input, total_output, total_cached, False)
    savings = gene_savings * 0.001  # rough: each gene hit saves ~$0.001 LLM call

    db.close()
    return {
        "task_id": task_id,
        "steps": len(rows),
        "total_tokens": total_input + total_output,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cached_tokens": total_cached,
        "cost": round(cost, 4),
        "gene_map_hits": gene_savings,
        "savings_from_gene_map": round(savings, 4),
    }


def daily_cost(days: int = 7) -> list[dict]:
    """Cost per day for the last N days."""
    db = _get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = db.execute("""
        SELECT date(timestamp) as day,
               SUM(input_tokens), SUM(output_tokens), SUM(cached_tokens),
               SUM(gene_map_hit)
        FROM cost_events WHERE timestamp >= ?
        GROUP BY day ORDER BY day DESC
    """, (cutoff,)).fetchall()
    db.close()

    result = []
    for r in rows:
        cost = _calc_cost(r[1], r[2], r[3], False)
        result.append({
            "date": r[0],
            "cost": round(cost, 4),
            "tokens": r[1] + r[2],
            "gene_hits": r[4],
            "gene_savings": round(r[4] * 0.001, 4),
        })
    return result


def savings_summary() -> dict:
    """How much gene_map and headroom have saved."""
    db = _get_db()
    total_cost = _calc_cost(
        sum(r[0] for r in db.execute("SELECT SUM(input_tokens) FROM cost_events").fetchall() if r[0]) or 0,
        sum(r[0] for r in db.execute("SELECT SUM(output_tokens) FROM cost_events").fetchall() if r[0]) or 0,
        sum(r[0] for r in db.execute("SELECT SUM(cached_tokens) FROM cost_events").fetchall() if r[0]) or 0,
        False,
    )
    gene_hits = db.execute("SELECT COUNT(*) FROM cost_events WHERE gene_map_hit=1").fetchone()[0]
    db.close()

    return {
        "total_cost": round(total_cost, 4),
        "gene_map_hits": gene_hits,
        "gene_map_savings": round(gene_hits * 0.001, 4),
        "headroom_estimate": round(total_cost * 0.4, 4),  # headroom saves ~40% on input
    }
