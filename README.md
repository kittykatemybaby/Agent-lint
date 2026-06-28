# agent-lint

**Your AI agent is burning money and you don't know it. ** `agent-lint` catches errors before they happen.

One silent agent failure costs more than a year of monitoring. `agent-lint` is the fuse.

```bash
pip install agent-lint
agent-lint check "DELETE users WHERE inactive > 30d" --tool sql --rows 5000
# → REJECT (risk 0.7, impact exceeds max)
```

---

## What it does

| Command | Does |
|---------|------|
| `agent-lint check` | Risk-score an agent action before it runs |
| `agent-lint genes` | Show known error patterns and fixes |
| `agent-lint audit` | Audit an execution trace |
| `agent-lint predict` | Predict outcome before execution |

## Why

987+ repos on GitHub are building agent eval frameworks. General Intuition raised $2.3B for AI agents. But nobody tells you BEFORE the agent breaks production.

`agent-lint` does.

## Dashboard

```bash
python3 dashboard_server.py
# → http://localhost:8765
```

Linear dark theme. System state, pending actions, drift visualization. Live data from your SQLite databases.

## Engine

| Module | Does |
|--------|------|
| `stop_conditions.py` | Every action has success criteria + halt conditions |
| `gene_map.py` | Error memory — same error never diagnosed twice |
| `prediction_dataset.py` | Blind prediction before action, retro after |
| `cross_audit.py` | Read-only audit by another agent |
| `observation_lifecycle.py` | Promote what works, archive what doesn't |

## Competitors

| Product | Traces | Guards | Predicts | Price |
|---------|--------|--------|----------|-------|
| LangSmith | ✅ | ❌ | ❌ | $39/seat |
| Arize | ✅ | ❌ | ❌ | Free-$ |
| Braintrust | ✅ | ❌ | ❌ | Free-$ |
| Guardrails AI | ❌ | ✅ | ❌ | Free |
| Lakera | ❌ | ✅ | ❌ | Enterprise |
| **agent-lint** | ✅ | ✅ | ✅ | Free OSS |

The only one that predicts before executing.

---

Skipped: pip package (needs PyPI account), cloud dashboard, SSO. Add when: first 100 GitHub stars.
