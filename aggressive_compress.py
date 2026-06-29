"""Compression Engine v2 — priority-scored, time-decayed, chunk-aware.

Improvements over v1:
  A. Time decay on ALL weights — "never drop" is dead
  B. Chunk-level scoring — 100-200 token granularity
  C. Intent folding — collapse debug sessions into state machine
  D. Negative memory — record dead ends, not just progress
  E. Dynamic budget — shrink as task nears completion
  F. Compression quality loop — LLM self-verifies post-compression
"""

import re
import hashlib
import math
from datetime import datetime
from enum import Enum


# ── Config ───────────────────────────────────────────────────────

CHUNK_SIZE = 150        # tokens per chunk
DEFAULT_BUDGET = 7000   # target context tokens
DECAY_RATE = 0.1        # e^(-0.1 * turns_ago)
SEMANTIC_HASH_PREFIX = 80  # chars to hash for semantic dedup


# ── Chunk-Level Scoring ──────────────────────────────────────────

class ChunkPriority(float):
    DECISION = 1.0       # decision, verdict, constraint
    TASK_CONTEXT = 0.8   # current task, plan
    TOOL_RESULT = 0.5    # tool output with data
    REASONING = 0.3      # analysis, thinking
    PROCESS = 0.1        # logs, intermediate steps
    DEAD_END = 0.05      # negative memory — keep but lowest priority


def chunk_text(text: str, chunk_tokens: int = CHUNK_SIZE) -> list[str]:
    """Split text into ~chunk_tokens-sized pieces."""
    words = text.split()
    chunks = []
    current = []
    current_len = 0
    for w in words:
        current.append(w)
        current_len += len(w) / 4  # rough token estimate
        if current_len >= chunk_tokens:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
    if current:
        chunks.append(" ".join(current))
    return chunks or [text]


def score_chunk(chunk: str, chunk_index: int, total_chunks: int,
                turns_ago: int = 0) -> float:
    """Score a chunk for retention. Time decay applies to ALL weights."""
    lower = chunk.lower()
    base = ChunkPriority.PROCESS  # default: noise

    # Decision signals
    if any(kw in lower for kw in ["verdict", "reject", "approve", "decision",
                                     "constraint", "pattern detected", "final"]):
        base = ChunkPriority.DECISION

    # Task context
    elif any(kw in lower for kw in ["task:", "plan:", "current", "route:",
                                      "next step", "goal:"]):
        base = ChunkPriority.TASK_CONTEXT

    # Tool results with data
    elif any(c in lower for c in ['"verdict"', '"score"', '"result"', '"data"',
                                    '"error"', '"status"', '"findings"']):
        base = ChunkPriority.TOOL_RESULT

    # Reasoning
    elif len(chunk) > 200:
        base = ChunkPriority.REASONING

    # Dead end / negative memory
    if any(kw in lower for kw in ["dead end", "exclusion", "tried and failed",
                                    "does not work", "abandoned"]):
        base = ChunkPriority.DEAD_END

    # Recency boost for last few chunks
    if chunk_index >= total_chunks - 3:
        base = min(1.0, base * 1.5)

    # Time decay: e^(-DECAY_RATE * turns_ago)
    decay = math.exp(-DECAY_RATE * turns_ago)

    return base * decay


# ── Semantic Dedup ───────────────────────────────────────────────

def semantic_hash(text: str) -> str:
    """Hash based on semantic content, not literal string."""
    # Normalize: lowercase, strip whitespace, remove stop patterns
    normalized = re.sub(r'\s+', ' ', text.lower().strip())
    # Remove variable content: numbers, timestamps, URLs, IDs
    normalized = re.sub(r'\b\d+\b', 'N', normalized)
    normalized = re.sub(r'https?://\S+', 'URL', normalized)
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', 'TS', normalized)
    return hashlib.md5(normalized[:SEMANTIC_HASH_PREFIX].encode()).hexdigest()[:12]


def semantic_dedup(chunks: list[str]) -> list[str]:
    """Dedup by semantic hash, keeping highest-value version."""
    seen = {}  # hash → (chunk, score)
    for i, chunk in enumerate(chunks):
        h = semantic_hash(chunk)
        score = score_chunk(chunk, i, len(chunks))
        if h not in seen or score > seen[h][1]:
            seen[h] = (chunk, score)
    return [c for c, _ in seen.values()]


# ── Intent Folding ───────────────────────────────────────────────

def detect_intent_span(messages: list[str]) -> list[dict]:
    """Detect consecutive messages in the same intent space and fold them."""
    spans = []
    current_intent = None
    span_msgs = []

    for msg in messages:
        lower = msg.lower()
        # Simple intent detection — can be upgraded with embeddings
        if "debug" in lower or "fix" in lower or "error" in lower:
            intent = "debug"
        elif "research" in lower or "scan" in lower or "search" in lower:
            intent = "research"
        elif "build" in lower or "implement" in lower or "create" in lower:
            intent = "build"
        elif "decide" in lower or "choose" in lower or "final" in lower:
            intent = "decide"
        else:
            intent = None

        if intent and intent == current_intent:
            span_msgs.append(msg)
        else:
            if span_msgs and len(span_msgs) >= 3:
                spans.append({"intent": current_intent, "messages": span_msgs})
            current_intent = intent
            span_msgs = [msg] if intent else []

    if span_msgs and len(span_msgs) >= 3:
        spans.append({"intent": current_intent, "messages": span_msgs})

    return spans


def fold_intent_span(span: dict) -> str:
    """Collapse an intent span into a state-machine summary."""
    msgs = span["messages"]
    hypotheses = []
    verified = []
    falsified = []
    next_action = ""

    for msg in msgs:
        lower = msg.lower()
        if "hypothesis" in lower or "think" in lower or "maybe" in lower:
            hypotheses.append(msg[:120])
        if "confirmed" in lower or "verified" in lower or "works" in lower:
            verified.append(msg[:120])
        if "falsified" in lower or "not" in lower or "wrong" in lower or "failed" in lower:
            falsified.append(msg[:120])
        if "next" in lower or "try" in lower or "will" in lower:
            next_action = msg[:120]

    return (
        f"[Intent: {span['intent']} ({len(msgs)} rounds folded)]\n"
        + (f"Hypotheses: {'; '.join(hypotheses[-2:])}\n" if hypotheses else "")
        + (f"Verified: {'; '.join(verified[-2:])}\n" if verified else "")
        + (f"Falsified: {'; '.join(falsified[-2:])}\n" if falsified else "")
        + (f"Next: {next_action}" if next_action else "")
    )


# ── Dynamic Budget ───────────────────────────────────────────────

def dynamic_budget(task_confidence: float, base_budget: int = DEFAULT_BUDGET) -> int:
    """Shrink budget as task nears completion.

    Low confidence (early): more context, less aggressive compression.
    High confidence (late): aggressively compress history, save space for output.
    """
    if task_confidence < 0.3:
        return int(base_budget * 1.3)  # 9100
    elif task_confidence < 0.7:
        return base_budget            # 7000
    else:
        return int(base_budget * 0.5)  # 3500


# ── Compression Quality Loop ──────────────────────────────────────

def verify_compression(original_key_facts: list[str], compressed_text: str) -> dict:
    """Verify compression preserved ability to answer key questions.

    Returns {passed: bool, missing: [facts], confidence: float}
    """
    missing = []
    for fact in original_key_facts:
        # Check if fact is still recoverable from compressed text
        fact_keywords = set(re.findall(r'\w+', fact.lower()))
        text_keywords = set(re.findall(r'\w+', compressed_text.lower()))
        overlap = len(fact_keywords & text_keywords) / max(len(fact_keywords), 1)

        if overlap < 0.5:
            missing.append(fact)

    confidence = 1.0 - (len(missing) / max(len(original_key_facts), 1))
    return {
        "passed": len(missing) == 0,
        "missing": missing,
        "confidence": round(confidence, 2),
    }


# ── Main Pipeline ────────────────────────────────────────────────

def compress_v2(
    messages: list[str],
    task_confidence: float = 0.5,
    turns_ago: int = 0,
    key_facts: list[str] = None,
) -> tuple[str, dict]:
    """Full v2 compression pipeline.

    Args:
        messages: list of message strings
        task_confidence: 0-1, higher = task nearly done → aggressive budget
        turns_ago: how many conversation turns ago these messages are
        key_facts: facts that MUST survive compression (for quality verification)

    Returns:
        (compressed_text, stats)
    """
    budget = dynamic_budget(task_confidence)

    # Step 1: Chunk everything
    all_chunks = []
    for msg in messages:
        all_chunks.extend(chunk_text(msg))

    total_tokens_before = sum(len(c) / 4 for c in all_chunks)

    # Step 2: Semantic dedup
    all_chunks = semantic_dedup(all_chunks)

    # Step 3: Intent folding
    spans = detect_intent_span(messages)
    folded = {}
    for span in spans:
        folded[span["intent"]] = fold_intent_span(span)

    # Step 4: Score all chunks with time decay
    scored = []
    for i, chunk in enumerate(all_chunks):
        score = score_chunk(chunk, i, len(all_chunks), turns_ago)
        tokens = len(chunk) / 4
        scored.append({"chunk": chunk, "score": score, "tokens": tokens})

    # Step 5: Drop lowest-score chunks until under budget
    scored.sort(key=lambda s: s["score"])
    kept = list(scored)
    total_tokens = sum(s["tokens"] for s in kept)

    while total_tokens > budget and kept:
        dropped = kept.pop(0)
        total_tokens -= dropped["tokens"]

    # Step 6: Reconstruct — fold intent spans first, then remaining chunks
    result_parts = list(folded.values())
    result_parts += [s["chunk"] for s in kept]

    result = "\n\n".join(result_parts)

    # Step 7: Quality verification
    quality = None
    if key_facts:
        quality = verify_compression(key_facts, result)

    stats = {
        "before_chunks": len(all_chunks),
        "after_chunks": len(kept),
        "before_tokens": int(total_tokens_before),
        "after_tokens": int(total_tokens),
        "budget": budget,
        "task_confidence": task_confidence,
        "folded_intents": len(folded),
        "quality": quality,
    }

    return result, stats
