# agent-lint

[![CI](https://github.com/kittykatemybaby/Agent-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/kittykatemybaby/Agent-lint/actions)
[![MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`agent-lint` checks agent actions and traces before execution. It surfaces risky inputs and suspicious execution paths using rule-based heuristics — no LLM calls at runtime.

---

## What problem this solves

Deploying AI agents that call tools (SQL, HTTP, email) without guardrails results in two failure modes:

1. **Silent damage.** An agent runs `UPDATE orders SET status='refunded'` on 50,000 rows. You find out from angry customers.
2. **Repeated mistakes.** Same error pattern hits your agent every session. It re-diagnoses from scratch each time, burning tokens and time.

`agent-lint` adds pre-execution checks and error memory so these get caught early.

---

## How it works

### Check an action

```bash
$ agent-lint check "DELETE FROM orders WHERE status = 'pending'" --tool sql --rows 5000
{
  "verdict": "REJECT",
  "risk_score": 0.70,
  "patterns_detected": ["Impact (5000) exceeds max (1000)"]
}
```

The tool compares the action against registered specs (max rows, reversibility, known risky patterns). No LLM involved.

### Check a safe action

```bash
$ agent-lint check "SELECT * FROM orders WHERE created > '2026-01-01'" --tool sql --rows 100
{
  "verdict": "APPROVE",
  "risk_score": 0.30,
  "patterns_detected": []
}
```

### Show known error patterns

```bash
$ agent-lint genes
DeepSeek API timeout      → retry (delay: 3s, max 2)
Rate limit 429             → backoff (delay: 60s)
Database connection refused → retry (delay: 5s, max 2)
Permission denied          → escalate (human needed)
```

### Audit a trace file

```bash
$ agent-lint audit trace.json
{
  "steps": 12,
  "errors": 1,
  "warnings": 2,
  "findings": [
    {"step": 7, "severity": "error", "description": "Timeout on POST /refund"},
    {"step": 7, "severity": "warning", "description": "Step 7 took 6200ms (slow)"}
  ]
}
```

---

## Dashboard (optional)

```bash
python3 dashboard_server.py
# → http://localhost:8765
```

A local web UI showing system state, pending actions, and drift visualization. No external services needed.

![Dashboard](screenshot.png)

---

## What agent-lint is not

- **Not a guarantee.** Risk scoring is heuristic. A low score doesn't prove safety. A high score doesn't prove danger. It's a flagging tool, not a proof system.
- **Not real-time enforcement.** It checks actions before you deploy them. It does not intercept live agent calls (that's the refutability engine, coming later).
- **Not a replacement for human review.** Final decisions on high-risk actions should involve a human.
- **Not a tracing platform.** It audits traces you provide. It does not collect them automatically.

---

## How scoring works

Risk is a weighted sum of:

| Factor | Weight | Example |
|--------|--------|---------|
| Tool type base risk | 0.1–0.4 | SQL writes are riskier than reads |
| Impact (rows affected) | 0–0.3 | 50,000 rows > 100 rows |
| Irreversibility | +0.1 | DELETE is permanent |
| Known pattern match | +0.15–0.4 | "bulk_delete", "user_data_access" |
| Reversibility check | 0 for reversible actions | file writes can be rolled back |

Thresholds:
- **≥0.70** → REJECT
- **0.40–0.69** → ESCALATE (human review)
- **<0.40** → APPROVE

`--rows` exists because impact matters. A `DELETE` on 5 rows is different from 50,000. The tool needs to know the blast radius.

---

## Modules

| Module | Purpose |
|--------|---------|
| `stop_conditions.py` | Declares success criteria and halt conditions per pipeline step |
| `gene_map.py` | SQLite-backed error memory — stores known error→fix mappings, 1ms lookup |
| `prediction_dataset.py` | Blind-predict before action, compare with actual after, track accuracy |
| `cross_audit.py` | Reads pipeline output and flags signal quality, stuck sequences, data gaps |
| `observation_lifecycle.py` | Promotes patterns that work, archives patterns that don't |

All zero external dependencies. Pure Python 3.10+.

---

## Install

```bash
git clone https://github.com/kittykatemybaby/Agent-lint.git
cd Agent-lint
chmod +x agent-lint
bash demo.sh
```

Or via pip from the repo:

```bash
pip install git+https://github.com/kittykatemybaby/Agent-lint.git
```

---

## Limitations

- Scoring is rule-based, not learned. It won't improve on its own without updating the pattern definitions.
- No built-in event collection. You bring traces to it; it doesn't hook into your agent runtime.
- Gene Map ships with 5 pre-seeded patterns. It grows as you record fixes — an empty Gene Map provides no value.
- Cross-audit reads local JSON files. It doesn't connect to observability platforms.
- Dashboard is local-only. No auth, no multi-tenancy.

---

## Real example

A fintech team runs `agent-lint` in CI to gate their AI agent's generated SQL:

```yaml
# .github/workflows/agent-check.yml
- name: Check agent actions
  run: |
    agent-lint check "$(cat agent_output.sql)" --tool sql --rows "$(wc -l < affected.csv)"
    agent-lint audit latest_trace.json
```

If the agent generates a `DELETE` on 10,000 rows, CI blocks the deploy.

---

## License

MIT. Built by [Kitty Kate](https://x.com/KittyKatemybaby).
