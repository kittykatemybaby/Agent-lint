"""Replay Engine — store and replay agent execution traces.

Stores events in SQLite. Replays by task_id in chronological order.
No streaming, no WebSocket, no UI. Just the engine.

Integration: every tool_call → replay.record(). Debug → replay.replay().
"""

import json, sqlite3, time
from pathlib import Path
from dataclasses import dataclass, field

REPLAY_DB = Path(__file__).parent / "replay.db"

def _db():
    db = sqlite3.connect(str(REPLAY_DB))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL, step INTEGER, event TEXT, tool TEXT,
        args TEXT, result TEXT, duration_ms REAL, cost REAL,
        input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
        status TEXT DEFAULT 'success', error TEXT,
        timestamp TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_replay_task ON events(task_id, step)")
    return db

def record(task_id: str, step: int, event: str, tool: str = "",
           args: dict = None, result: str = "", duration_ms: float = 0,
           cost: float = 0, status: str = "success", error: str = ""):
    db = _db()
    db.execute("""INSERT INTO events (task_id,step,event,tool,args,result,
        duration_ms,cost,status,error,timestamp)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (task_id, step, event, tool, json.dumps(args or {}), result[:5000],
         duration_ms, cost, status, error, time.time()))
    db.commit(); db.close()

def replay(task_id: str) -> list[dict]:
    db = _db()
    rows = db.execute("SELECT step,event,tool,args,result,duration_ms,cost,status,error,timestamp FROM events WHERE task_id=? ORDER BY step", (task_id,)).fetchall()
    db.close()
    return [{"step":r[0],"event":r[1],"tool":r[2],"args":json.loads(r[3]) if r[3] else {},
             "result":r[4],"duration_ms":r[5],"cost":r[6],"status":r[7],"error":r[8],"timestamp":r[9]} for r in rows]

def list_tasks(limit: int = 20) -> list[str]:
    db = _db()
    rows = db.execute("SELECT DISTINCT task_id FROM events ORDER BY MAX(timestamp) DESC LIMIT ?", (limit,)).fetchall()
    db.close()
    return [r[0] for r in rows]

# ponytail: self-test
if __name__ == "__main__":
    record("test-1", 1, "thinking", result="I need to search")
    record("test-1", 2, "tool_call", tool="search", args={"q":"test"}, duration_ms=200, cost=0.001)
    record("test-1", 3, "response", result="done")
    r = replay("test-1")
    assert len(r) == 3 and r[1]["tool"] == "search"
    print(f"✓ {len(r)} events replayed")
