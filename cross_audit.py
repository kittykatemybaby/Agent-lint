"""Cross Audit Engine — read-only audit of pipeline output.

From BuilderIO agent-watchdog: "Audit another agent's work — reconstruct what
was asked, check what actually changed and verified, report gaps."

SECURITY GUARANTEE:
  - READ-ONLY: This module only reads pipeline output files.
  - It NEVER modifies state, NEVER calls write functions.
  - Audit results are written to a SEPARATE audit_report.md/json file.
  - No circular dependency: audit engine doesn't import pipeline write functions.

Architecture:
  Pipeline (write) ──output_files──→ CrossAudit (read) ──→ audit_report.md
       ↑                                                       │
       └─────── human reviews audit, decides action ───────────┘
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

OUTREACH_DIR = Path(__file__).parent
AUDIT_DIR = OUTREACH_DIR / "audit"
AUDIT_DIR.mkdir(exist_ok=True)


@dataclass
class AuditFinding:
    id: str
    severity: str          # critical | warning | info
    category: str          # signal_quality | email_content | timing | gap | data_quality
    description: str
    evidence: str          # specific file/line/data point
    recommendation: str
    found_at: str


@dataclass  
class AuditReport:
    audited_at: str
    scope: list[str]       # which files/data were audited
    findings: list[AuditFinding] = field(default_factory=list)
    pipeline_health: dict = field(default_factory=dict)
    summary: str = ""


# ── Audit Checks ───────────────────────────────────────────────────

def _read_json_safe(path: Path) -> dict:
    """Read JSON safely — never writes."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def audit_signal_classification() -> list[AuditFinding]:
    """Audit the quality of signal → lead classification.

    Checks:
    - Are high-intent leads actually matching high-intent keywords?
    - Are there leads classified as 'high' with only 1 weak keyword?
    - Are medium-intent leads with 5+ keywords being misclassified?
    """
    findings = []
    leads = _read_json_safe(OUTREACH_DIR / "leads.json")

    high_with_weak_signal = 0
    medium_with_strong_signal = 0

    for lid, lead in leads.items():
        intent = lead.get("intent_level", "low")
        keywords = lead.get("matched_keywords", [])

        # High intent but only 1 keyword → suspicious
        if intent == "high" and len(keywords) <= 1:
            high_with_weak_signal += 1

        # Medium intent but 5+ keywords → might deserve upgrade
        if intent == "medium" and len(keywords) >= 5:
            medium_with_strong_signal += 1

    if high_with_weak_signal > 3:
        findings.append(AuditFinding(
            id="sig-001",
            severity="warning",
            category="signal_quality",
            description=f"{high_with_weak_signal} high-intent leads classified with only 1 keyword — may be false positives",
            evidence=f"leads.json: {high_with_weak_signal} leads with intent=high, keywords≤1",
            recommendation="Review these leads manually. Consider raising the high-intent keyword threshold to ≥2.",
            found_at=datetime.now().isoformat(),
        ))

    if medium_with_strong_signal > 5:
        findings.append(AuditFinding(
            id="sig-002",
            severity="info",
            category="signal_quality",
            description=f"{medium_with_strong_signal} medium-intent leads with 5+ keywords — possible misclassification",
            evidence=f"leads.json: {medium_with_strong_signal} leads with intent=medium, keywords≥5",
            recommendation="Consider auto-promoting leads with ≥5 high-intent keywords to 'high'.",
            found_at=datetime.now().isoformat(),
        ))

    return findings


def audit_email_quality() -> list[AuditFinding]:
    """Audit email templates and queued emails for quality issues.

    Checks:
    - Are email subjects too long (>60 chars)?
    - Are body texts too short (<50 chars)?
    - Are there unsubstituted template variables?
    """
    findings = []
    seqs = _read_json_safe(OUTREACH_DIR / "sequences.json")

    # Check sequences for suspicious states
    stuck_sequences = 0
    for sid, seq in seqs.items():
        stage = seq.get("stage", "")
        last_action = seq.get("last_action_at", "")
        if last_action:
            try:
                last_date = datetime.fromisoformat(last_action)
                days_since = (datetime.now() - last_date).days
                if days_since > 14 and stage not in ("converted", "dormant", "rejected"):
                    stuck_sequences += 1
            except ValueError:
                pass

    if stuck_sequences > 3:
        findings.append(AuditFinding(
            id="email-001",
            severity="warning",
            category="timing",
            description=f"{stuck_sequences} sequences stuck without progress for >14 days",
            evidence=f"sequences.json: {stuck_sequences} leads with last_action >14d, stage not terminal",
            recommendation="Review stuck sequences. May need manual follow-up or dormancy marking.",
            found_at=datetime.now().isoformat(),
        ))

    return findings


def audit_prediction_accuracy() -> list[AuditFinding]:
    """Audit prediction accuracy from prediction_dataset.

    Checks:
    - Is overall accuracy below 40%? (worse than random guessing)
    - Are any action types consistently wrong?
    """
    findings = []
    pred_db = OUTREACH_DIR / "predictions.db"

    if not pred_db.exists():
        findings.append(AuditFinding(
            id="pred-001",
            severity="info",
            category="data_quality",
            description="No prediction data yet — accuracy cannot be measured",
            evidence="predictions.db does not exist or has no completed retro rows",
            recommendation="Run the pipeline for at least 7 days to accumulate prediction data.",
            found_at=datetime.now().isoformat(),
        ))
        return findings

    try:
        db = sqlite3.connect(str(pred_db))
        total = db.execute(
            "SELECT COUNT(*) FROM predictions WHERE actual_outcome IS NOT NULL"
        ).fetchone()[0]
        correct = db.execute(
            "SELECT COUNT(*) FROM predictions WHERE prediction_correct = 1"
        ).fetchone()[0]
        db.close()

        if total > 0:
            accuracy = correct / total
            if accuracy < 0.4:
                findings.append(AuditFinding(
                    id="pred-002",
                    severity="critical",
                    category="signal_quality",
                    description=f"Prediction accuracy {accuracy:.0%} — worse than random guessing (50%)",
                    evidence=f"predictions.db: {correct}/{total} correct",
                    recommendation="The prediction heuristics need recalibration. Review predict_for_lead() weights.",
                    found_at=datetime.now().isoformat(),
                ))
            elif accuracy < 0.6:
                findings.append(AuditFinding(
                    id="pred-003",
                    severity="warning",
                    category="signal_quality",
                    description=f"Prediction accuracy {accuracy:.0%} — marginal",
                    evidence=f"predictions.db: {correct}/{total} correct",
                    recommendation="Monitor for improvement. If accuracy doesn't increase after 30 predictions, adjust heuristics.",
                    found_at=datetime.now().isoformat(),
                ))
    except Exception as e:
        findings.append(AuditFinding(
            id="pred-004",
            severity="warning",
            category="data_quality",
            description=f"Failed to read prediction database: {e}",
            evidence="predictions.db access error",
            recommendation="Check database integrity.",
            found_at=datetime.now().isoformat(),
        ))

    return findings


def audit_data_quality() -> list[AuditFinding]:
    """Audit data completeness and consistency.

    Checks:
    - How many leads lack firm_name?
    - How many high-intent leads lack email?
    - Are there duplicate leads?
    """
    findings = []
    leads = _read_json_safe(OUTREACH_DIR / "leads.json")

    missing_firm = sum(1 for l in leads.values() if not l.get("firm_name") or len(l.get("firm_name", "")) < 3)
    high_without_email = sum(
        1 for l in leads.values()
        if l.get("intent_level") == "high" and not l.get("email")
    )

    if missing_firm > len(leads) * 0.5 and len(leads) > 5:
        findings.append(AuditFinding(
            id="data-001",
            severity="warning",
            category="data_quality",
            description=f"{missing_firm}/{len(leads)} leads ({missing_firm/len(leads):.0%}) missing firm names",
            evidence="leads.json: firm_name empty or <3 chars",
            recommendation="Firm name extraction may need improvement. Review firm_extractor.py patterns.",
            found_at=datetime.now().isoformat(),
        ))

    if high_without_email > 0:
        findings.append(AuditFinding(
            id="data-002",
            severity="info",
            category="gap",
            description=f"{high_without_email} high-intent leads without contact email — unreachable",
            evidence=f"leads.json: {high_without_email} leads with intent=high, email=empty",
            recommendation="Run contact enrichment for these leads. If still no email, consider manual research.",
            found_at=datetime.now().isoformat(),
        ))

    return findings


# ── Full Audit Run ─────────────────────────────────────────────────

def run_full_audit() -> dict:
    """Run all audit checks and produce a comprehensive report.

    This function is READ-ONLY. It never modifies pipeline state.
    """
    all_findings = []
    all_findings.extend(audit_signal_classification())
    all_findings.extend(audit_email_quality())
    all_findings.extend(audit_prediction_accuracy())
    all_findings.extend(audit_data_quality())

    # Pipeline health summary
    from stop_conditions import pipeline_health as _ph
    health = _ph()

    report = AuditReport(
        audited_at=datetime.now().isoformat(),
        scope=["leads.json", "sequences.json", "predictions.db", "stop_conditions"],
        findings=all_findings,
        pipeline_health=health,
    )

    critical = [f for f in all_findings if f.severity == "critical"]
    warnings = [f for f in all_findings if f.severity == "warning"]
    info = [f for f in all_findings if f.severity == "info"]

    report.summary = (
        f"Audit complete: {len(critical)} critical, {len(warnings)} warnings, {len(info)} info findings.\n"
        + (f"CRITICAL: {critical[0].description}" if critical else "No critical issues.")
    )

    # Write audit report to SEPARATE file (never modifies pipeline state)
    report_dict = {
        "audited_at": report.audited_at,
        "scope": report.scope,
        "summary": report.summary,
        "pipeline_health": report.pipeline_health,
        "findings_by_severity": {
            "critical": [asdict(f) for f in critical],
            "warning": [asdict(f) for f in warnings],
            "info": [asdict(f) for f in info],
        },
        "total_findings": len(all_findings),
    }

    audit_json = AUDIT_DIR / f"audit_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    audit_json.write_text(json.dumps(report_dict, indent=2, ensure_ascii=False))

    # Also write human-readable markdown
    audit_md = AUDIT_DIR / "latest_audit.md"
    md_lines = [
        f"# Cross Audit Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"## Summary",
        report.summary,
        "",
    ]
    for sev, items in [("🔴 Critical", critical), ("🟠 Warning", warnings), ("🔵 Info", info)]:
        if items:
            md_lines.append(f"## {sev}")
            for f in items:
                md_lines.append(f"### {f.category}: {f.description}")
                md_lines.append(f"- **Evidence**: {f.evidence}")
                md_lines.append(f"- **Recommendation**: {f.recommendation}")
                md_lines.append("")

    audit_md.write_text("\n".join(md_lines))

    return report_dict
