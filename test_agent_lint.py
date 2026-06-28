#!/usr/bin/env python3
"""agent-lint test suite — run with: python3 test_agent_lint.py"""

import json
import subprocess
import sys
import tempfile
import os

PASS = 0
FAIL = 0

def run(cmd, expect_exit=0):
    global PASS, FAIL
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout) if result.stdout else {}
    except:
        data = {"raw": result.stdout[:100]}
    
    if result.returncode == expect_exit:
        PASS += 1
        print(f"  ✓ {cmd[:60]}...")
    else:
        FAIL += 1
        print(f"  ✗ {cmd[:60]}...")
        print(f"    expected exit {expect_exit}, got {result.returncode}")
        print(f"    stdout: {result.stdout[:200]}")
    return data

# Ensure agent-lint is executable
os.chmod("agent-lint", 0o755)

print("=== check: safe action ===")
run('./agent-lint check "Read status report" --tool api_call --rows 1', expect_exit=0)

print("=== check: borderline action ===")
data = run('./agent-lint check "SELECT * FROM users" --tool sql --rows 10', expect_exit=1)
assert data.get("verdict") == "ESCALATE"

print("=== check: risky action ===")
data = run('./agent-lint check "DELETE FROM payments" --tool sql --rows 50000', expect_exit=1)
assert data.get("verdict") == "REJECT", f"Expected REJECT, got {data.get('verdict')}"

print("=== check: HTTP GET (safe) ===")
run('./agent-lint check "GET /api/status" --tool http_get --rows 1', expect_exit=0)

print("=== check: HTTP DELETE (risky) ===")
run('./agent-lint check "DELETE /api/users/1" --tool http_delete --rows 1', expect_exit=1)

print("=== check: shell exec ===")
data = run('./agent-lint check "rm -rf /var/log" --tool shell_exec --rows 1', expect_exit=1)
assert data.get("verdict") in ("REJECT", "ESCALATE"), f"Expected REJECT/ESCALATE"

print("=== check: email (low risk) ===")
run('./agent-lint check "Send password reset" --tool email_send --rows 1', expect_exit=0)

print("=== genes ===")
data = run('./agent-lint genes', expect_exit=0)
raw = subprocess.run('./agent-lint genes', shell=True, capture_output=True, text=True).stdout
assert "DeepSeek" in raw, "Gene map should contain DeepSeek entry"

print("=== audit ===")
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump({
        "steps": [
            {"action": "SELECT 1", "tool": "sql", "duration_ms": 100},
            {"action": "DROP TABLE bad_idea", "tool": "sql", "duration_ms": 15000, "error": "permission denied"}
        ]
    }, f)
    trace_path = f.name

data = run(f'./agent-lint audit {trace_path}', expect_exit=0)
assert data.get("errors", 0) >= 1, "Should find at least 1 error"
assert data.get("warnings", 0) >= 1, "Should find at least 1 warning"
os.unlink(trace_path)

print("=== predict ===")
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump({"action": "bulk_refund_all", "tool": "sql", "params": {"rows": 5000}}, f)
    pred_path = f.name

data = run(f'./agent-lint predict {pred_path}', expect_exit=0)
assert "predicted_outcome" in data, "Prediction should include predicted_outcome"
os.unlink(pred_path)

print(f"\n{'='*40}")
print(f"  {PASS} passed, {FAIL} failed")
print(f"{'='*40}")

sys.exit(0 if FAIL == 0 else 1)
