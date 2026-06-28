"""Critic — structured decision reviewer with cognitive isolation.

Rules:
  1. Never output free-form reasoning to Builder
  2. Output only: {verdict, score, reasons}
  3. Builder sees verdict + score. Builder NEVER sees critic's chain-of-thought.

Integration:
  Builder makes proposal → Critic reviews → structured signal returned
  Builder reads: verdict, score, reasons (no internal reasoning)
"""

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


class Verdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"


@dataclass
class CriticSignal:
    verdict: Verdict
    score: float          # 0-1 confidence
    reasons: list[str]    # machine-readable tags
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Heuristic checks (no LLM, fast) ──────────────────────────────

CRITIC_CHECKS = [
    {
        "tag": "overengineering",
        "check": lambda proposal: len(proposal.get("files", [])) > 5 and proposal.get("complexity", "low") == "low",
        "explanation": "Too many files for stated complexity",
    },
    {
        "tag": "missing_failure_handling",
        "check": lambda proposal: "error" not in str(proposal).lower() and "except" not in str(proposal).lower() and proposal.get("stage", "") == "production",
        "explanation": "No error handling in production proposal",
    },
    {
        "tag": "no_tests",
        "check": lambda proposal: "test" not in str(proposal).lower() and proposal.get("type", "") == "code",
        "explanation": "Code proposal without test plan",
    },
    {
        "tag": "scope_creep",
        "check": lambda proposal: proposal.get("estimated_hours", 0) > 8 and proposal.get("priority", "medium") == "low",
        "explanation": "Large scope but low priority",
    },
    {
        "tag": "security_risk",
        "check": lambda proposal: any(kw in str(proposal).lower() for kw in ["password", "token", "secret", "api_key"]),
        "explanation": "Credential handling without explicit security review",
    },
    {
        "tag": "dependency_blast",
        "check": lambda proposal: proposal.get("new_deps", 0) > 5,
        "explanation": "Too many new dependencies at once",
    },
]


def review_proposal(
    proposal: dict,
    strict_mode: bool = False,
) -> CriticSignal:
    """Review a builder proposal and return structured signal.

    Builder CAN see the verdict, score, and reasons.
    Builder CANNOT see the internal checking logic.
    """
    reasons = []
    for check in CRITIC_CHECKS:
        try:
            if check["check"](proposal):
                reasons.append(check["tag"])
        except Exception:
            pass

    n_issues = len(reasons)
    if n_issues == 0:
        return CriticSignal(verdict=Verdict.APPROVE, score=0.9, reasons=[])

    if n_issues >= 3 or (strict_mode and n_issues >= 1):
        return CriticSignal(
            verdict=Verdict.REJECT,
            score=round(0.3 + n_issues * 0.1, 2),
            reasons=reasons,
        )

    return CriticSignal(
        verdict=Verdict.ESCALATE,
        score=round(0.5 + n_issues * 0.1, 2),
        reasons=reasons,
    )


def review_code_change(
    diff: str,
    file_count: int = 1,
    new_deps: int = 0,
) -> CriticSignal:
    """Quick review of a code change."""
    return review_proposal({
        "type": "code",
        "diff": diff[:500],
        "files": [""] * file_count,
        "new_deps": new_deps,
        "stage": "development",
    })


def to_dict(signal: CriticSignal) -> dict:
    return {
        "verdict": signal.verdict.value,
        "score": signal.score,
        "reasons": signal.reasons,
        "timestamp": signal.timestamp,
    }
