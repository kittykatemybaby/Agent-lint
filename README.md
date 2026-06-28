# agent-lint

![Dashboard](screenshot.png)

**Predict before you break production.** One silent agent failure costs more than a year of monitoring.

```bash
git clone https://github.com/kittykatemybaby/agent-lint.git
cd agent-lint
./agent-lint check "DELETE users WHERE inactive > 30d" --tool sql --rows 5000
# → REJECT (risk 0.7, impact exceeds max)
```

---

## What

| Command | Does |
|---------|------|
| `check "action" --tool sql --rows N` | Risk-score before execution |
| `genes` | Known error patterns + fixes |
| `audit trace.json` | Scan execution trace for issues |
| `predict action.json` | Predict outcome before running |

## Why

987+ repos on GitHub are building agent eval frameworks. Patronus just raised $50M for agent simulation. But **nobody stops the agent BEFORE it breaks production.**

agent-lint does.

## Dashboard

```bash
python3 dashboard_server.py
# → http://localhost:8765
```

Linear dark theme. System state panel. Pending action queue with Approve/Reject/Simulate. Real-time drift visualization (p5.js).

## Engine (5 modules, zero deps)

| Module | Does |
|--------|------|
| `stop_conditions.py` | Every action declares success + halt + escalate |
| `gene_map.py` | Error memory — same error, 1ms lookup, $0 re-diagnosis |
| `prediction_dataset.py` | Blind-predict before action, retro after |
| `cross_audit.py` | Second agent audits first agent's output |
| `observation_lifecycle.py` | Promote what works, archive what doesn't |

## Competitors

| Product | Traces | Guards | **Predicts** | Price |
|---------|--------|--------|-------------|-------|
| LangSmith | ✅ | ❌ | ❌ | $39/seat |
| Arize | ✅ | ❌ | ❌ | Free |
| Braintrust | ✅ | ❌ | ❌ | Free |
| Lakera | ❌ | ✅ | ❌ | Enterprise |
| **agent-lint** | ✅ | ✅ | **✅** | Free |

**Only one that predicts before executing.**

---

## Install

```bash
git clone https://github.com/kittykatemybaby/agent-lint.git
cd agent-lint
chmod +x agent-lint
./agent-lint check "your action here" --tool api_call
```

Python 3.10+. Zero external dependencies.

---

Built by Kitty Kate · [@KittyKatemybaby](https://x.com/KittyKatemybaby) · MIT
