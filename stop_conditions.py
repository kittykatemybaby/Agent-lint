"""Stop Condition Layer — every pipeline action must declare success + stop.

From loop-library: "A good loop answers four questions:
  What is it trying to accomplish?
  How will it know whether the latest attempt worked?
  What should it do with what it learned?
  When should it finish or ask for help?"

This module wraps pipeline steps with explicit stop conditions.
If a step exceeds its stop condition, it halts and escalates.
"""

import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Callable, Optional
from enum import Enum


class StopReason(str, Enum):
    SUCCESS = "success"
    EXHAUSTED = "exhausted"       # max attempts reached
    DEGRADED = "degraded"         # quality below threshold
    TIMEOUT = "timeout"           # wall-clock limit exceeded
    EXTERNAL = "external"         # external signal (API down, rate limited)
    HUMAN_NEEDED = "human_needed"  # requires human judgment


@dataclass
class StopCondition:
    """Defines when a pipeline step should stop and what success looks like."""
    name: str
    max_attempts: int = 3
    max_duration_seconds: int = 600
    quality_threshold: float = 0.7      # 0-1: what counts as "good enough"
    escalate_after_failures: int = 3    # consecutive failures before human escalation
    
    # Tracked state
    attempts: int = 0
    consecutive_failures: int = 0
    started_at: float = 0.0
    last_result: dict = field(default_factory=dict)
    stop_reason: Optional[StopReason] = None

    def start(self):
        self.started_at = time.time()
        self.attempts = 0
        self.consecutive_failures = 0
        self.stop_reason = None

    def check(self, result_ok: bool, quality: float = 1.0) -> tuple[bool, StopReason | None]:
        """Check if we should continue or stop. Returns (should_continue, stop_reason)."""
        self.attempts += 1

        # 1. Success — quality above threshold
        if result_ok and quality >= self.quality_threshold:
            self.stop_reason = StopReason.SUCCESS
            return False, StopReason.SUCCESS

        # 2. Max attempts exhausted
        if self.attempts >= self.max_attempts:
            self.consecutive_failures += 1
            self.stop_reason = StopReason.EXHAUSTED
            return False, StopReason.EXHAUSTED

        # 3. Timeout
        elapsed = time.time() - self.started_at
        if elapsed > self.max_duration_seconds:
            self.consecutive_failures += 1
            self.stop_reason = StopReason.TIMEOUT
            return False, StopReason.TIMEOUT

        # 4. Quality degraded
        if not result_ok:
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.escalate_after_failures:
                self.stop_reason = StopReason.DEGRADED
                return False, StopReason.DEGRADED

        # Continue
        if not result_ok:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0

        return True, None

    def needs_human(self) -> bool:
        """Check if this step needs human escalation."""
        return self.consecutive_failures >= self.escalate_after_failures


# ── Pipeline Step Definitions ──────────────────────────────────────

PIPELINE_STOPS = {
    "signal_scan": StopCondition(
        name="signal_scan",
        max_attempts=3,
        max_duration_seconds=300,
        quality_threshold=0.5,   # At least 50% of scanned sources returned data
        escalate_after_failures=3,
    ),
    "firm_extraction": StopCondition(
        name="firm_extraction",
        max_attempts=2,
        max_duration_seconds=120,
        quality_threshold=0.6,   # 60% of leads got firm names extracted
        escalate_after_failures=2,
    ),
    "contact_enrichment": StopCondition(
        name="contact_enrichment",
        max_attempts=2,
        max_duration_seconds=180,
        quality_threshold=0.3,   # Only 30% expected — many Reddit leads have no public email
        escalate_after_failures=2,
    ),
    "dedup": StopCondition(
        name="dedup",
        max_attempts=2,
        max_duration_seconds=60,
        quality_threshold=0.9,
        escalate_after_failures=2,
    ),
    "outreach_cycle": StopCondition(
        name="outreach_cycle",
        max_attempts=2,
        max_duration_seconds=300,
        quality_threshold=0.8,
        escalate_after_failures=2,
    ),
    "report_generation": StopCondition(
        name="report_generation",
        max_attempts=2,
        max_duration_seconds=60,
        quality_threshold=1.0,   # Report must generate or fail
        escalate_after_failures=1,
    ),
    "email_send": StopCondition(
        name="email_send",
        max_attempts=3,
        max_duration_seconds=30,
        quality_threshold=1.0,   # Email must send or fail
        escalate_after_failures=2,
    ),
}


def get_stop(name: str) -> StopCondition:
    """Get or create a stop condition for a pipeline step."""
    if name not in PIPELINE_STOPS:
        PIPELINE_STOPS[name] = StopCondition(name=name)
    return PIPELINE_STOPS[name]


def reset_all_stops():
    """Reset all stop conditions for a fresh pipeline run."""
    for sc in PIPELINE_STOPS.values():
        sc.start()


def pipeline_health() -> dict:
    """Return health status of all pipeline stops."""
    return {
        name: {
            "attempts": sc.attempts,
            "failures": sc.consecutive_failures,
            "stopped": sc.stop_reason is not None,
            "reason": sc.stop_reason.value if sc.stop_reason else None,
            "needs_human": sc.needs_human(),
        }
        for name, sc in PIPELINE_STOPS.items()
    }
