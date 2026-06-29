"""Aggressive Compression — target 7k context, from 13k.

Strategy: priority-scored truncation, not message-count windowing.
Each message gets a retention score. Drop from bottom until under budget.

Score factors:
  +1.0  decision / constraint / failure record
  +0.8  current task / plan
  +0.5  tool result with actionable data
  +0.3  reasoning chain
  +0.1  process log / "thinking" / intermediate steps
"""

import re
from enum import Enum


class MessagePriority(float):
    CRITICAL = 1.0    # Never drop: decisions, constraints, failures
    HIGH = 0.8        # Current task, plan, routing decisions
    MEDIUM = 0.5      # Tool results with useful data
    LOW = 0.3         # Reasoning, analysis
    NOISE = 0.1       # Process logs, intermediate steps, "thinking"


def score_message(msg: dict, msg_index: int, total_msgs: int) -> float:
    """Score a message for retention priority."""
    role = msg.get("role", "")
    content = str(msg.get("content", ""))
    lower = content.lower()

    # Critical: decisions, failures, constraints
    if any(kw in lower for kw in ["verdict", "reject", "fail", "constraint", "decision", "pattern"]):
        # But not if it's just a tool log mentioning these words
        if role in ("assistant", "user") or "verdict" in lower:
            return MessagePriority.CRITICAL

    # High: current task, plan, routing
    if any(kw in lower for kw in ["task:", "plan:", "routing", "next step", "current"]):
        return MessagePriority.HIGH

    # Recency boost: last 5 messages
    if msg_index >= total_msgs - 5:
        return MessagePriority.HIGH

    # Medium: tool results with data
    if role == "tool" and len(content) > 50:
        return MessagePriority.MEDIUM

    # Low: reasoning
    if role == "assistant" and len(content) > 100:
        return MessagePriority.LOW

    # Noise: process, thinking, short messages
    return MessagePriority.NOISE


def estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 chars ≈ 1 token for English, 2 chars ≈ 1 for Chinese."""
    en_chars = len(re.findall(r'[a-zA-Z0-9\s]', text))
    zh_chars = len(text) - en_chars
    return int(en_chars / 4 + zh_chars / 2)


def priority_compress(messages: list[dict], token_budget: int = 7000) -> tuple[list[dict], dict]:
    """Compress to token budget by dropping lowest-priority messages first.

    Returns (compressed_messages, stats).
    """
    total = len(messages)

    # Score all messages
    scored = []
    for i, msg in enumerate(messages):
        score = score_message(msg, i, total)
        tokens = estimate_tokens(str(msg.get("content", "")))
        scored.append({"msg": msg, "score": score, "tokens": tokens, "index": i})

    # Sort by score ascending (lowest first = first to drop)
    # But keep original order for critical messages
    to_keep = list(scored)
    total_tokens = sum(s["tokens"] for s in to_keep)

    # Drop from bottom until under budget
    dropped = []
    while total_tokens > token_budget:
        # Find lowest-scored message
        lowest_idx = min(range(len(to_keep)), key=lambda i: to_keep[i]["score"])
        lowest = to_keep.pop(lowest_idx)
        dropped.append(lowest)
        total_tokens -= lowest["tokens"]

    # Sort kept messages by original index
    to_keep.sort(key=lambda s: s["index"])

    return (
        [s["msg"] for s in to_keep],
        {
            "before": len(messages),
            "after": len(to_keep),
            "before_tokens": sum(s["tokens"] for s in scored),
            "after_tokens": total_tokens,
            "dropped": len(dropped),
            "budget": token_budget,
            "dropped_types": {
                "critical": sum(1 for d in dropped if d["score"] >= 0.8),
                "medium": sum(1 for d in dropped if 0.3 <= d["score"] < 0.8),
                "noise": sum(1 for d in dropped if d["score"] < 0.3),
            },
        },
    )


def headroom_compress(text: str) -> str:
    """Use headroom to compress tool output. 60-95% reduction."""
    try:
        from headroom import compress
        result = compress([{"role": "system", "content": text}])
        return str(result)
    except Exception:
        return text


def full_compression_pipeline(messages: list[dict], token_budget: int = 7000) -> list[dict]:
    """Full pipeline: headroom → dedup → priority compress."""
    # Step 1: Headroom compress tool outputs
    for msg in messages:
        if msg.get("role") == "tool" and len(str(msg.get("content", ""))) > 500:
            try:
                msg["content"] = headroom_compress(str(msg["content"]))
            except Exception:
                pass

    # Step 2: Dedup
    seen = {}
    deduped = []
    for msg in messages:
        key = str(msg.get("content", ""))[:100]
        if key not in seen:
            seen[key] = True
            deduped.append(msg)

    # Step 3: Priority-scored truncation
    result, stats = priority_compress(deduped, token_budget)
    result.append({
        "role": "system",
        "content": f"[Compression: {stats['before']}→{stats['after']} msgs, {stats['before_tokens']}→{stats['after_tokens']} tokens]"
    })
    return result
