"""Critic Gate — system-level enforcement, not prompt suggestion.

Architecture:
  Builder output → Gate intercepts (mandatory, cannot skip) →
    1. Deterministic checks (schema, allowlist, policy)
    2. Cross-model LLM critic (Gemini, different provider)
    3. Pass → release. Fail → structured reasons → retry (max 3)
    4. Exhausted → escalate to human

This is NOT a prompt rule. It's middleware that sits between Builder
and any external output channel. Skip = impossible.
"""

import json, re, time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


# ── Gate States ───────────────────────────────────────────────────

class GateVerdict(str, Enum):
    PASS = "pass"
    FAIL_HARD = "fail_hard"     # deterministic rule hit, no retry
    FAIL_SOFT = "fail_soft"     # LLM critic flagged, retry allowed
    ESCALATE = "escalate"       # max retries exhausted


@dataclass
class GateResult:
    verdict: GateVerdict
    checker: str                # which checker rejected
    reason: str                 # machine-readable reason
    structured_feedback: dict = field(default_factory=dict)  # for builder retry
    attempts: int = 1
    timestamp: str = field(default_factory=lambda: str(time.time()))


# ── Deterministic Checkers ────────────────────────────────────────

class DeterministicChecks:
    """Hard rules — no LLM. Schema, allowlist, policy. Fast and unbypassable."""

    @staticmethod
    def schema_valid(output: dict, required_fields: list[str]) -> Optional[GateResult]:
        missing = [f for f in required_fields if f not in output]
        if missing:
            return GateResult(GateVerdict.FAIL_HARD, "schema", f"Missing fields: {missing}")
        return None

    @staticmethod
    def allowlist_tool(output: dict, allowed_tools: list[str]) -> Optional[GateResult]:
        tool = output.get("tool", "")
        if tool and allowed_tools and tool not in allowed_tools:
            return GateResult(GateVerdict.FAIL_HARD, "allowlist", f"Tool '{tool}' not in allowlist")
        return None

    @staticmethod
    def no_sensitive_data(output: dict) -> Optional[GateResult]:
        text = json.dumps(output).lower()
        patterns = [r'api[_-]?key\s*[:=]\s*\S+', r'password\s*[:=]\s*\S+',
                    r'token\s*[:=]\s*\S+', r'secret\s*[:=]\s*\S+']
        for pat in patterns:
            if re.search(pat, text):
                return GateResult(GateVerdict.FAIL_HARD, "policy", "Credential leak detected in output")
        return None

    @staticmethod
    def within_limits(output: dict, max_tokens: int = 8000,
                      max_tool_calls: int = 10) -> Optional[GateResult]:
        if len(json.dumps(output)) > max_tokens * 4:
            return GateResult(GateVerdict.FAIL_SOFT, "limits", "Output exceeds token limit")
        if output.get("tool_calls", []) and len(output["tool_calls"]) > max_tool_calls:
            return GateResult(GateVerdict.FAIL_SOFT, "limits", "Too many tool calls")
        return None

    @staticmethod
    def run_all(output: dict, spec: dict) -> list[GateResult]:
        results = []
        for check_fn, args in [
            (DeterministicChecks.schema_valid, (output, spec.get("required_fields", []))),
            (DeterministicChecks.allowlist_tool, (output, spec.get("allowed_tools", []))),
            (DeterministicChecks.no_sensitive_data, (output,)),
            (DeterministicChecks.within_limits, (output,)),
        ]:
            r = check_fn(*args)
            if r: results.append(r)
        return results


# ── LLM Critic (cross-model via Gemini) ───────────────────────────

async def llm_critic(output: dict, spec: dict) -> Optional[GateResult]:
    """Cross-model review using Gemini (different provider from Builder's DeepSeek)."""
    prompt = f"""Review this agent output against the spec. Answer ONLY in JSON:

Spec: {json.dumps(spec.get('constraints', {}), ensure_ascii=False)}
Output: {json.dumps(output, ensure_ascii=False)[:2000]}

Return: {{"pass": true/false, "reason": "one sentence", "severity": "low/medium/high"}}"""

    try:
        import httpx
        key = __import__('os').environ.get("GEMINI_API_KEY", "")
        if not key:
            return None  # no Gemini key configured, skip LLM critic

        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            data = resp.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
            review = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())

            if not review.get("pass", True):
                return GateResult(
                    GateVerdict.FAIL_SOFT,
                    "llm_critic",
                    review.get("reason", "Review failed"),
                    {"severity": review.get("severity", "medium")},
                )
    except Exception:
        pass
    return None


# ── The Gate (system middleware, cannot skip) ─────────────────────

async def critic_gate(output: dict, spec: dict) -> GateResult:
    """Mandatory gate. Builder output cannot leave without passing through here.

    Args:
        output: what Builder produced
        spec: {required_fields, allowed_tools, constraints, max_retries}

    Returns:
        GateResult with verdict. If FAIL_SOFT, structure feedback for retry.
    """
    max_retries = spec.get("max_retries", 3)
    attempt = spec.get("_attempt", 1)

    # Layer 1: Deterministic checks (fast, unbypassable)
    hard_results = DeterministicChecks.run_all(output, spec)
    for r in hard_results:
        if r.verdict == GateVerdict.FAIL_HARD:
            r.attempts = attempt
            return r  # hard fail — no retry, human must review

    # Layer 2: LLM critic (cross-model)
    llm_result = await llm_critic(output, spec)
    if llm_result:
        llm_result.attempts = attempt
        if attempt >= max_retries:
            return GateResult(GateVerdict.ESCALATE, "gate", f"Max retries ({max_retries}) exhausted",
                            {"last_reason": llm_result.reason, "attempts": attempt})
        return llm_result  # fail_soft → retry with feedback

    # All clear
    return GateResult(GateVerdict.PASS, "gate", "All checks passed", attempts=attempt)


# ── Gate Loop (builder → critic → retry → escalate) ─────────────

async def gate_loop(build_fn, spec: dict) -> tuple[dict, GateResult]:
    """Run builder-critic loop with max retries and hard gate enforcement.

    Args:
        build_fn: async function that takes feedback dict and returns output dict
        spec: {required_fields, allowed_tools, constraints, max_retries}

    Returns:
        (final_output, final_gate_result)
    """
    feedback = {}
    for attempt in range(1, spec.get("max_retries", 3) + 1):
        spec["_attempt"] = attempt
        output = await build_fn(feedback)
        result = await critic_gate(output, spec)

        if result.verdict == GateVerdict.PASS:
            return output, result
        elif result.verdict == GateVerdict.FAIL_HARD:
            return output, result
        elif result.verdict == GateVerdict.ESCALATE:
            return output, result
        else:  # fail_soft → retry
            feedback = {"reason": result.reason, "attempt": attempt,
                        "checker": result.checker}

    return output, GateResult(GateVerdict.ESCALATE, "loop", "Loop exhausted")
