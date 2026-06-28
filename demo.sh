#!/usr/bin/env bash
# agent-lint quickstart demo
set -e

echo "=== agent-lint Quickstart ==="
echo ""

echo "1. Check a low-risk action:"
./agent-lint check "Send weekly report email" --tool email_send --rows 10
echo ""

echo "2. Check a high-risk action (should REJECT):"
./agent-lint check "DELETE FROM payments" --tool sql --rows 10000
echo ""

echo "3. Show error gene map:"
./agent-lint genes
echo ""

echo "4. Predict an action outcome:"
cat > /tmp/demo_action.json << 'EOF'
{"action": "bulk_refund_all_orders", "tool": "sql", "params": {"rows": 5000}}
EOF
./agent-lint predict /tmp/demo_action.json
rm /tmp/demo_action.json
echo ""

echo "5. Audit a sample trace:"
cat > /tmp/demo_trace.json << 'EOF'
{
  "steps": [
    {"action": "SELECT * FROM users", "tool": "sql", "duration_ms": 200},
    {"action": "POST /api/refund", "tool": "http_post", "duration_ms": 8200, "error": "timeout"}
  ]
}
EOF
./agent-lint audit /tmp/demo_trace.json
rm /tmp/demo_trace.json
echo ""

echo "=== Done ==="
echo "Dashboard: python3 dashboard_server.py → http://localhost:8765"
