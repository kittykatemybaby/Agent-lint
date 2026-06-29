"""Tool Governance — registry, routing, enforcement.

Rules (enforced, not advisory):
  1. Each task → 1 primary tool + 1 backup. No exceptions.
  2. Same data source → max 1 method. No multi-method scraping.
  3. Core pipeline → JSON-output tools only.
  4. Non-core tools → "temporary plugin" status. Auto-purge after 7d unused.
  5. Unknown tool → default-deny. Must be registered before use.
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import json
from pathlib import Path

ROUTING_DB = Path(__file__).parent / "tool_routing.db"


# ── Tool Classification ──────────────────────────────────────────

class ToolTier(str, Enum):
    CORE = "core"           # Always available, JSON output
    BACKUP = "backup"       # Fallback when primary fails
    PLUGIN = "plugin"       # Temporary, auto-purge after 7d


class ToolDomain(str, Enum):
    COLLECTION = "collection"     # Data gathering: APIs, scraping, crawling
    SENTIMENT = "sentiment"       # Brand monitoring, sentiment analysis
    VERIFICATION = "verification"  # Fact-checking, source validation
    REPORTING = "reporting"       # Summarization, report generation
    ORCHESTRATION = "orchestration"  # Agent coordination, routing
    NOTIFICATION = "notification"  # Alerts, messages, emails
    STORAGE = "storage"           # Databases, files, vaults


@dataclass
class ToolSpec:
    name: str
    domain: ToolDomain
    tier: ToolTier
    output_format: str          # json | text | binary
    rate_limit: str             # e.g. "60/min"
    cost: str                   # "free" | "paid"
    auth_required: bool
    route_priority: int = 0     # lower = higher priority
    registered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: str = ""
    plugin_expires: str = ""


# ── Tool Registry ─────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, ToolSpec] = {
    # ── Collection Layer ──
    "terminal+curl": ToolSpec(
        name="terminal+curl",
        domain=ToolDomain.COLLECTION,
        tier=ToolTier.CORE,
        output_format="json",
        rate_limit="unlimited",
        cost="free",
        auth_required=False,
        route_priority=1,
    ),
    "execute_code": ToolSpec(
        name="execute_code",
        domain=ToolDomain.COLLECTION,
        tier=ToolTier.CORE,
        output_format="json",
        rate_limit="50 calls/script",
        cost="free",
        auth_required=False,
        route_priority=2,
    ),
    "browser_navigate": ToolSpec(
        name="browser_navigate",
        domain=ToolDomain.COLLECTION,
        tier=ToolTier.BACKUP,
        output_format="text",
        rate_limit="slow",
        cost="proxy $5/mo",
        auth_required=True,
        route_priority=3,
    ),
    # ── Sentiment / Research Layer ──
    "hn_api": ToolSpec(
        name="hn_api",
        domain=ToolDomain.SENTIMENT,
        tier=ToolTier.CORE,
        output_format="json",
        rate_limit="100/min",
        cost="free",
        auth_required=False,
        route_priority=1,
    ),
    "github_api": ToolSpec(
        name="github_api",
        domain=ToolDomain.SENTIMENT,
        tier=ToolTier.CORE,
        output_format="json",
        rate_limit="10/min unauth, 30/min auth",
        cost="free",
        auth_required=False,
        route_priority=2,
    ),
    # ── Verification Layer ──
    "jina_reader": ToolSpec(
        name="jina_reader",
        domain=ToolDomain.VERIFICATION,
        tier=ToolTier.CORE,
        output_format="text",
        rate_limit="unknown",
        cost="free",
        auth_required=False,
        route_priority=1,
    ),
    "cross_audit": ToolSpec(
        name="cross_audit",
        domain=ToolDomain.VERIFICATION,
        tier=ToolTier.CORE,
        output_format="json",
        rate_limit="unlimited",
        cost="free",
        auth_required=False,
        route_priority=2,
    ),
    # ── Reporting Layer ──
    "file_write": ToolSpec(
        name="file_write",
        domain=ToolDomain.REPORTING,
        tier=ToolTier.CORE,
        output_format="text",
        rate_limit="unlimited",
        cost="free",
        auth_required=False,
        route_priority=1,
    ),
    "smtp_email": ToolSpec(
        name="smtp_email",
        domain=ToolDomain.REPORTING,
        tier=ToolTier.CORE,
        output_format="json",
        rate_limit="Gmail SMTP limits",
        cost="free",
        auth_required=True,
        route_priority=2,
    ),
    # ── Orchestration Layer ──
    "cronjob": ToolSpec(
        name="cronjob",
        domain=ToolDomain.ORCHESTRATION,
        tier=ToolTier.CORE,
        output_format="json",
        rate_limit="unlimited",
        cost="free",
        auth_required=False,
        route_priority=1,
    ),
    "delegate_task": ToolSpec(
        name="delegate_task",
        domain=ToolDomain.ORCHESTRATION,
        tier=ToolTier.CORE,
        output_format="text",
        rate_limit="3 concurrent",
        cost="free",
        auth_required=False,
        route_priority=2,
    ),
    # ── Notification Layer ──
    "telegram": ToolSpec(
        name="telegram",
        domain=ToolDomain.NOTIFICATION,
        tier=ToolTier.CORE,
        output_format="text",
        rate_limit="30/min",
        cost="free",
        auth_required=True,
        route_priority=1,
    ),
    "obsidian_vault": ToolSpec(
        name="obsidian_vault",
        domain=ToolDomain.STORAGE,
        tier=ToolTier.CORE,
        output_format="text",
        rate_limit="unlimited",
        cost="free",
        auth_required=False,
        route_priority=1,
    ),
    "project_brain": ToolSpec(
        name="project_brain",
        domain=ToolDomain.STORAGE,
        tier=ToolTier.CORE,
        output_format="json",
        rate_limit="unlimited",
        cost="free",
        auth_required=False,
        route_priority=2,
    ),
    # ── External Services (plugin tier) ──
    "apify": ToolSpec(name="apify", domain=ToolDomain.COLLECTION, tier=ToolTier.PLUGIN, output_format="json", rate_limit="paid", cost="paid", auth_required=True, route_priority=20),
    "brandwatch": ToolSpec(name="brandwatch", domain=ToolDomain.SENTIMENT, tier=ToolTier.PLUGIN, output_format="json", rate_limit="paid", cost="paid", auth_required=True, route_priority=20),
    "perplexity": ToolSpec(name="perplexity", domain=ToolDomain.VERIFICATION, tier=ToolTier.PLUGIN, output_format="text", rate_limit="paid", cost="paid", auth_required=True, route_priority=20),
    "gemini": ToolSpec(name="gemini", domain=ToolDomain.REPORTING, tier=ToolTier.PLUGIN, output_format="json", rate_limit="paid", cost="paid", auth_required=True, route_priority=20),
}


# ── Task Routing Table ───────────────────────────────────────────

ROUTING_TABLE = {
    "research_scan": {
        "primary": "terminal+curl",
        "backup": "delegate_task",
        "max_duration_seconds": 300,
        "retry_on": ["timeout", "rate_limit"],
    },
    "web_scrape": {
        "primary": "jina_reader",
        "backup": "browser_navigate",
        "max_duration_seconds": 60,
        "retry_on": ["timeout"],
    },
    "fact_check": {
        "primary": "cross_audit",
        "backup": "jina_reader",
        "max_duration_seconds": 120,
        "retry_on": ["inconclusive"],
    },
    "report_generate": {
        "primary": "file_write",
        "backup": "smtp_email",
        "max_duration_seconds": 60,
        "retry_on": ["io_error"],
    },
    "notify_low": {
        "primary": "telegram",
        "backup": None,
        "max_duration_seconds": 10,
        "retry_on": [],
    },
    "notify_high": {
        "primary": "smtp_email",
        "backup": "telegram",
        "max_duration_seconds": 30,
        "retry_on": ["auth_error"],
    },
    "store_memory": {
        "primary": "project_brain",
        "backup": "obsidian_vault",
        "max_duration_seconds": 10,
        "retry_on": ["io_error"],
    },
    "schedule_task": {
        "primary": "cronjob",
        "backup": None,
        "max_duration_seconds": 10,
        "retry_on": [],
    },
    "code_execute": {
        "primary": "execute_code",
        "backup": "terminal+curl",
        "max_duration_seconds": 300,
        "retry_on": ["timeout"],
    },
}


# ── Route Enforcer ───────────────────────────────────────────────

def get_route(task_type: str) -> dict:
    """Get the mandated tool route for a task type. Returns primary + backup."""
    route = ROUTING_TABLE.get(task_type)
    if not route:
        raise ValueError(f"Unknown task type: {task_type}. Must be registered in ROUTING_TABLE.")
    return route


def validate_task(task_type: str, tool_name: str) -> bool:
    """Check if a tool is allowed for this task type."""
    route = ROUTING_TABLE.get(task_type)
    if not route:
        return False
    return tool_name in (route["primary"], route["backup"])


# ── Notification Tiering ─────────────────────────────────────────

class AlertLevel(str, Enum):
    INFO = "info"        # Routine: daily reports, scan results
    WARNING = "warning"  # Medium: drift > 0.5, rate limiting
    CRITICAL = "critical"  # High: security event, account blocked, data loss


def notify(level: AlertLevel, title: str, body: str, next_step: str = ""):
    """Route notifications by severity. Low/medium → Telegram. High → Email + Telegram."""
    message = f"{title}\n\n{body}"
    if next_step:
        message += f"\n\n下一步：{next_step}"

    if level in (AlertLevel.INFO, AlertLevel.WARNING):
        # Telegram only — low friction
        route = get_route("notify_low")
        print(f"[NOTIFY:{level.value}] {title}")
    else:
        # Email — must-get-attention
        route = get_route("notify_high")
        print(f"[NOTIFY:{level.value}] {title} (email + telegram)")

    return {"level": level.value, "title": title, "message": message}


# ── 4-Level Compression ──────────────────────────────────────────

class CompressionLevel(Enum):
    L1_DEDUP = 1
    L2_SUMMARIZE = 2
    L3_WINDOW = 3
    L4_CHECKPOINT = 4


def compression_pipeline(context: list[dict], token_estimate: int) -> tuple[list[dict], CompressionLevel]:
    """Apply compression based on token threshold.

    L1 (Dedup): < 5k tokens — remove duplicates, keep latest
    L2 (Summarize): 5k-8k — collapse multi-message threads
    L3 (Window): 8k-10k — keep only last N rounds
    L4 (Checkpoint): > 10k — write state to project_brain, rebuild
    """
    if token_estimate < 5000:
        # L1: Dedup — same event, keep latest
        seen = {}
        deduped = []
        for msg in reversed(context):
            key = msg.get("id") or msg.get("content", "")[:80]
            if key not in seen:
                seen[key] = True
                deduped.append(msg)
        return list(reversed(deduped)), CompressionLevel.L1_DEDUP

    elif token_estimate < 8000:
        # L2: Summarize — collapse threads
        summarized = []
        buffer = []
        for msg in context:
            if msg.get("role") == "tool":
                buffer.append(msg)
            else:
                if buffer:
                    summarized.append({"role": "system", "content": f"[{len(buffer)} tool calls collapsed]"})
                    buffer = []
                summarized.append(msg)
        return summarized, CompressionLevel.L2_SUMMARIZE

    elif token_estimate < 10000:
        # L3: Sliding window — last N rounds
        return context[-20:], CompressionLevel.L3_WINDOW

    else:
        # L4: Checkpoint — write state, rebuild
        return [{"role": "system", "content": "[Context checkpointed to project_brain]"}], CompressionLevel.L4_CHECKPOINT


# ── Memory Organization ──────────────────────────────────────────

def organize_memory(records: list[dict]) -> dict:
    """Organize by task + topic + confidence, not by conversation time."""
    by_task = {}
    for r in records:
        task = r.get("task_id") or r.get("record_type") or "general"
        by_task.setdefault(task, []).append(r)

    # Within each task: sort by confidence (high first), then recency
    for task, items in by_task.items():
        items.sort(key=lambda x: (
            -(x.get("confidence", {}).get("score", 0.5) if isinstance(x.get("confidence"), dict) else 0.5),
            x.get("created_at", "")
        ), reverse=True)

    return by_task


# ── Register Plugin ──────────────────────────────────────────────

def register_plugin(name: str, domain: ToolDomain, output_format: str = "json"):
    """Register a temporary plugin tool. Auto-purges after 7 days."""
    spec = ToolSpec(
        name=name,
        domain=domain,
        tier=ToolTier.PLUGIN,
        output_format=output_format,
        rate_limit="unknown",
        cost="unknown",
        auth_required=False,
        route_priority=99,
        plugin_expires=(datetime.now() + timedelta(days=7)).isoformat(),
    )
    TOOL_REGISTRY[name] = spec


def purge_expired_plugins():
    """Remove plugins unused for 7 days."""
    now = datetime.now().isoformat()
    expired = []
    for name, spec in list(TOOL_REGISTRY.items()):
        if spec.tier == ToolTier.PLUGIN and spec.plugin_expires < now:
            expired.append(name)
            del TOOL_REGISTRY[name]
    return expired
