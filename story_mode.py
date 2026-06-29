"""Story Mode — natural-language playback of agent workflows.

Turns raw execution traces into human-readable narratives.
Non-engineers can understand what the agent did, why, and whether to trust it.

Design: Apple + Linear + Notion aesthetic. Concise, narrative, visual.
"""

import json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TraceEvent:
    """Single event in an agent trace."""
    step: int
    event: str           # thinking, planning, search, tool_call, reflection, memory, response
    tool: str = ""
    arguments: dict = field(default_factory=dict)
    duration_ms: float = 0
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    response: str = ""
    status: str = "success"
    confidence: float = 0.0


# ── Narrative Generation ──────────────────────────────────────────

def _step_emoji(event: str) -> str:
    return {
        "thinking": "💭",
        "planning": "📋",
        "search": "🔍",
        "tool_call": "🔧",
        "reflection": "🪞",
        "memory": "🧠",
        "response": "💬",
        "error": "❌",
    }.get(event, "•")


def _format_duration(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        return f"{ms/60000:.1f}min"


def _format_cost(cost: float) -> str:
    if cost == 0:
        return "free"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.3f}"


def generate_story(events: list[TraceEvent], task_name: str = "") -> str:
    """Generate a natural-language narrative from trace events.

    Returns markdown suitable for display or email.
    """
    if not events:
        return "Nothing to tell."

    lines = []

    # Header
    lines.append(f"# {task_name or 'Agent Story'}")
    lines.append("")

    total_cost = sum(e.cost for e in events)
    total_tokens = sum(e.input_tokens + e.output_tokens for e in events)
    total_time = sum(e.duration_ms for e in events)
    errors = [e for e in events if e.status == "error"]

    # Summary box
    lines.append("> 📊 **Summary**")
    lines.append(f"> {len(events)} steps · {_format_duration(total_time)} · {_format_cost(total_cost)} · {total_tokens} tokens")
    if errors:
        lines.append(f"> ⚠️ {len(errors)} error(s) encountered")

    # What was the task?
    thinking_events = [e for e in events if e.event == "thinking"]
    if thinking_events:
        lines.append("")
        lines.append("## What was asked")
        lines.append(thinking_events[0].response[:200])

    # Step-by-step narrative
    lines.append("")
    lines.append("## What happened")

    for i, e in enumerate(events):
        emoji = _step_emoji(e.event)
        step_label = f"**Step {e.step}**"

        if e.event == "thinking":
            lines.append(f"{emoji} {step_label} — Thought for {_format_duration(e.duration_ms)}")
            if e.response:
                lines.append(f"   {e.response[:150]}")

        elif e.event == "planning":
            lines.append(f"{emoji} {step_label} — Made a plan")

        elif e.event == "search":
            lines.append(f"{emoji} {step_label} — Searched the web")
            if e.response:
                lines.append(f"   Query: _{e.response[:100]}_")

        elif e.event == "tool_call":
            cost_str = f" · {_format_cost(e.cost)}" if e.cost > 0 else ""
            status_icon = "✓" if e.status == "success" else "⚠️"
            lines.append(f"{emoji} {step_label} — Called `{e.tool}` {status_icon}{cost_str}")
            if e.arguments:
                args_preview = json.dumps(e.arguments, ensure_ascii=False)[:100]
                lines.append(f"   With: `{args_preview}`")
            if e.duration_ms > 0:
                lines.append(f"   Took {_format_duration(e.duration_ms)}")
            if e.status == "error" and e.response:
                lines.append(f"   Error: {e.response[:120]}")

        elif e.event == "reflection":
            lines.append(f"{emoji} {step_label} — Reflected on results")
            if e.response:
                lines.append(f"   {e.response[:150]}")

        elif e.event == "memory":
            lines.append(f"{emoji} {step_label} — Updated memory")

        elif e.event == "response":
            lines.append(f"{emoji} {step_label} — Delivered final response")

        elif e.event == "error":
            lines.append(f"❌ {step_label} — Something went wrong")
            if e.response:
                lines.append(f"   {e.response[:150]}")

        lines.append("")

    # Cost breakdown
    if total_cost > 0:
        lines.append("## Cost breakdown")
        lines.append("| Step | Tokens | Cost |")
        lines.append("|------|--------|------|")
        for e in events:
            if e.input_tokens > 0 or e.output_tokens > 0:
                tokens = f"{e.input_tokens}→{e.output_tokens}"
                cost = _format_cost(e.cost)
                lines.append(f"| {e.event} | {tokens} | {cost} |")
        lines.append("")

    # Trust verdict
    lines.append("## Can I trust this?")
    error_rate = len(errors) / max(len(events), 1)
    if error_rate == 0:
        lines.append("✅ All steps completed without errors.")
        lines.append("No retries were needed. This looks clean.")
    elif error_rate < 0.1:
        lines.append(f"⚠️ {len(errors)} out of {len(events)} steps had issues (mostly recovered).")
        lines.append("Minor hiccups, but the agent self-corrected.")
    else:
        lines.append(f"❌ {len(errors)} out of {len(events)} steps failed.")
        lines.append("This run had significant issues. Review the errors above before trusting the result.")

    return "\n".join(lines)


def generate_story_html(story_md: str) -> str:
    """Wrap markdown story in a clean HTML template (Linear + Apple aesthetic)."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Story</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  body {{ font-family: 'Inter', system-ui, sans-serif; background: #fafafa; color: #1a1a1a; max-width: 680px; margin: 60px auto; padding: 0 24px; font-feature-settings: 'cv01','ss03'; }}
  h1 {{ font-size: 28px; font-weight: 590; letter-spacing: -0.56px; margin-bottom: 8px; }}
  h2 {{ font-size: 20px; font-weight: 590; margin-top: 32px; margin-bottom: 12px; letter-spacing: -0.24px; }}
  blockquote {{ background: #f5f5f5; border-radius: 12px; padding: 16px 20px; margin: 16px 0; border: none; font-size: 14px; color: #555; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ color: #999; font-weight: 500; font-size: 12px; text-transform: uppercase; }}
  p {{ line-height: 1.6; color: #444; }}
</style>
</head>
<body>
{story_md.replace('## ', '<h2>').replace('# ', '<h1>').replace('**', '<strong>', 1).replace('**', '</strong>', 1) if False else story_md}
</body>
</html>"""
