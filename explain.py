"""Explain — why was this action blocked?

Generates natural-language explanations for agent-lint decisions.
Designed for non-engineers. Answer format: what happened, why, what to do.
"""

from dataclasses import dataclass

@dataclass
class Explanation:
    what: str       # what happened (one sentence)
    why: str        # why it was blocked (one sentence)
    fix: str        # what to do next (actionable)
    severity: str   # low | medium | high


def explain_rejection(tool: str, risk_score: float, patterns: list[str], fix_suggestion: str = "") -> Explanation:
    """Generate a human-readable explanation for a rejected/blocked action.

    Non-engineers can understand this without knowing what agent-lint is.
    """

    # What happened
    action_desc = {
        "sql": "tried to run a database query",
        "http_post": "tried to send data to an external service",
        "http_delete": "tried to delete data from an external service",
        "email_send": "tried to send an email",
        "shell_exec": "tried to run a shell command",
        "file_delete": "tried to delete a file",
    }.get(tool, f"tried to use the '{tool}' tool")

    what = f"Agent {action_desc}"
    if risk_score >= 0.7:
        what += " — this was blocked because it's too risky."

    # Why
    reasons = []
    for p in patterns:
        if "impact" in p.lower() or "exceeds" in p.lower():
            reasons.append(f"it would affect too many things at once")
        elif "irreversible" in p.lower():
            reasons.append(f"the action cannot be undone")
        elif "credential" in p.lower():
            reasons.append(f"it might expose sensitive credentials")
        elif "unknown tool" in p.lower():
            reasons.append(f"this tool hasn't been reviewed yet")
        else:
            reasons.append(p.lower())

    if not reasons:
        if risk_score >= 0.7:
            reasons.append("the overall risk level is too high")
        else:
            reasons.append("it triggered a safety rule")

    why = "Because " + " and because ".join(reasons[:2]) + "."

    # Fix
    if fix_suggestion:
        fix = fix_suggestion
    elif tool == "sql" and risk_score >= 0.7:
        fix = "Try limiting the query to fewer rows, or ask a human to review it first."
    elif tool == "shell_exec":
        fix = "Shell commands are not allowed by default. Submit a request for review."
    elif tool == "http_delete":
        fix = "Deletion operations need human approval. Add an approval step."
    else:
        fix = "Ask a human to review this action before running it."

    # Severity
    if risk_score >= 0.8:
        severity = "high"
    elif risk_score >= 0.5:
        severity = "medium"
    else:
        severity = "low"

    return Explanation(what=what, why=why, fix=fix, severity=severity)


def explain_approval(tool: str) -> Explanation:
    return Explanation(
        what=f"Agent used the '{tool}' tool — this passed all safety checks.",
        why="The action is reversible, low-impact, and doesn't match any risk patterns.",
        fix="No action needed.",
        severity="low",
    )


def explain_story(result: dict) -> str:
    """One-paragraph story for non-engineers."""
    verdict = result.get("verdict", "?").lower()
    if verdict == "approve":
        return "✅ This action was checked and approved. It's safe to run."
    elif verdict == "reject":
        exp = explain_rejection(
            result.get("tool", "?"),
            result.get("risk_score", 0),
            result.get("patterns_detected", []),
            result.get("fix_suggestion", ""),
        )
        return f"🛑 {exp.what} {exp.why} {exp.fix}"
    else:
        return f"⚠️ This action needs a human to review it before running."


# ponytail: self-test
if __name__ == "__main__":
    exp = explain_rejection("sql", 0.75, ["Impact (5000) exceeds max (1000)", "Operation is not reversible"])
    print(f"WHAT: {exp.what}")
    print(f"WHY: {exp.why}")
    print(f"FIX: {exp.fix}")
    print(f"SEVERITY: {exp.severity}")
    print("---")
    print(explain_story({"verdict": "REJECT", "tool": "sql", "risk_score": 0.75,
                         "patterns_detected": ["Impact (5000) exceeds max (1000)"],
                         "fix_suggestion": "Reduce to under 1000 rows"}))
