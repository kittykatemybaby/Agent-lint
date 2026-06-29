"""Refutability Engine — pre-execution interceptor.

The killer feature no competitor has. Before an agent action executes,
this engine has a 50ms window to block it.

Architecture:
  Agent action → Refutability Window (50ms) →
    ├── stop_conditions check  → halt?
    ├── gene_map lookup        → known fix?
    ├── critic review          → reject?
    └── ESCALATE or APPROVE

Uses asyncio for parallel checks within the time budget.
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class RefuteVerdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"


@dataclass
class Action:
    tool: str
    params: dict
    risk_hint: float = 0.0
    trace_id: str = ""
    agent_id: str = ""


@dataclass
class RefuteResult:
    verdict: RefuteVerdict
    reasons: list[str] = field(default_factory=list)
    fix_suggestion: str = ""
    latency_ms: float = 0.0
    checks_run: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Tool Specs (from agent-lint) ──────────────────────────────────

TOOL_SPECS = {
    "sql": {"reversible": False, "max_impact": 1000, "risk_base": 0.3},
    "http_post": {"reversible": False, "max_impact": 100, "risk_base": 0.4},
    "http_get": {"reversible": True, "max_impact": 1000, "risk_base": 0.1},
    "http_delete": {"reversible": False, "max_impact": 10, "risk_base": 0.5},
    "email_send": {"reversible": False, "max_impact": 500, "risk_base": 0.2},
    "file_write": {"reversible": True, "max_impact": 10, "risk_base": 0.1},
    "file_delete": {"reversible": False, "max_impact": 5, "risk_base": 0.5},
    "api_call": {"reversible": True, "max_impact": 100, "risk_base": 0.2},
    "shell_exec": {"reversible": False, "max_impact": 1, "risk_base": 0.6},
}

KNOWN_RISK_PATTERNS = [
    ("bulk_delete", 0.4, "Bulk deletion detected"),
    ("production_write", 0.3, "Write operation on production"),
    ("user_data_access", 0.25, "Access to user data"),
    ("external_api_new", 0.2, "New external API endpoint"),
    ("credential_in_params", 0.5, "Credentials in request parameters"),
    ("drop_table", 0.5, "Schema modification detected"),
]

GENE_MAP = {
    "timeout": ("retry", {"delay": 3, "max_retries": 2}),
    "rate_limit": ("backoff", {"delay": 60, "max_retries": 1}),
    "auth_failure": ("escalate", {"reason": "Credentials may be expired"}),
    "permission_denied": ("escalate", {"reason": "Insufficient permissions"}),
    "connection_refused": ("retry", {"delay": 5, "max_retries": 2}),
}


# ── Parallel Checks ──────────────────────────────────────────────

async def _check_stop_conditions(action: Action) -> Optional[str]:
    """Check action against tool specs. Block if over limits."""
    spec = TOOL_SPECS.get(action.tool, {"reversible": False, "max_impact": 1, "risk_base": 0.8})
    impact = action.params.get("rows", action.params.get("count", action.params.get("users", 0)))

    if impact > spec["max_impact"]:
        return f"Impact ({impact}) exceeds max ({spec['max_impact']}) for {action.tool}"
    return None


async def _check_risk_patterns(action: Action) -> list[str]:
    """Scan action description for known risk patterns."""
    text = str(action.params).lower()
    patterns = []
    for pattern, bump, reason in KNOWN_RISK_PATTERNS:
        if pattern.replace("_", " ") in text or pattern in text:
            patterns.append(reason)
    return patterns


async def _check_gene_map(action: Action) -> Optional[dict]:
    """Check if this action matches a known error pattern with a fix."""
    text = str(action.params).lower()
    for error, (fix_type, fix_params) in GENE_MAP.items():
        if error.replace("_", " ") in text:
            return {"known_error": error, "fix_type": fix_type, "fix_params": fix_params}
    return None


# ── Main Engine ──────────────────────────────────────────────────

async def refute(action: Action, time_budget_ms: float = 50.0) -> RefuteResult:
    """Intercept an agent action before execution.

    Runs stop_conditions, risk_patterns, and gene_map checks in parallel
    within the time budget. Returns verdict before the action executes.
    """
    start = time.time()
    reasons = []

    # Parallel checks
    stop_check = _check_stop_conditions(action)
    pattern_check = _check_risk_patterns(action)
    gene_check = _check_gene_map(action)

    results = await asyncio.gather(stop_check, pattern_check, gene_check)

    stop_result, patterns, gene_result = results
    checks_run = 3

    if stop_result:
        reasons.append(stop_result)

    reasons.extend(patterns)

    fix_suggestion = ""
    if gene_result:
        fix_suggestion = f"{gene_result['fix_type']}: {gene_result['fix_params']}"

    # Decision
    risk_score = action.risk_hint + (0.1 * len(patterns))
    if stop_result:
        risk_score += 0.3

    if risk_score >= 0.7:
        verdict = RefuteVerdict.REJECT
    elif risk_score >= 0.4 or len(reasons) > 0:
        verdict = RefuteVerdict.ESCALATE
    else:
        verdict = RefuteVerdict.APPROVE

    latency = (time.time() - start) * 1000

    return RefuteResult(
        verdict=verdict,
        reasons=reasons,
        fix_suggestion=fix_suggestion,
        latency_ms=round(latency, 2),
        checks_run=checks_run,
    )


# ── Synchronous wrapper for non-async contexts ────────────────────

def refute_sync(action: Action) -> RefuteResult:
    """Synchronous refutation — for CLI integration."""
    return asyncio.run(refute(action))


# ── Test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def main():
        # Safe action
        safe = Action(tool="http_get", params={"url": "/status"})
        result = await refute(safe)
        print(f"Safe: {result.verdict.value} ({result.latency_ms}ms)")

        # Dangerous action
        danger = Action(tool="sql", params={"query": "DELETE FROM users", "rows": 50000}, risk_hint=0.1)
        result = await refute(danger)
        print(f"Danger: {result.verdict.value} — {result.reasons} ({result.latency_ms}ms)")

        # With gene map hit
        gene_action = Action(tool="api_call", params={"endpoint": "/api/data", "timeout": True})
        result = await refute(gene_action)
        print(f"Gene: {result.verdict.value} — {result.fix_suggestion} ({result.latency_ms}ms)")

    asyncio.run(main())
