#!/usr/bin/env bash
# agent-lint quickstart — scan YOUR repo for risky agent actions
# Usage: bash <(curl -s https://raw.githubusercontent.com/kittykatemybaby/Agent-lint/master/quickstart.sh)
set -e

echo "agent-lint quickstart"
echo "====================="
echo ""

# Clone agent-lint
TMPDIR=$(mktemp -d)
git clone --quiet https://github.com/kittykatemybaby/Agent-lint.git "$TMPDIR/agent-lint" 2>/dev/null
cd "$TMPDIR/agent-lint"
chmod +x agent-lint

echo "Scanning your current directory for risky patterns..."
echo ""

FOUND=0

# Scan for SQL files with DELETE/UPDATE
for f in $(find "${OLDPWD:-.}" -name "*.sql" -o -name "*.py" 2>/dev/null | head -20); do
    if grep -q -i "DELETE\|DROP\|TRUNCATE" "$f" 2>/dev/null; then
        result=$(./agent-lint check "$(head -1 "$f")" --tool sql --rows 100 2>&1)
        verdict=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin).get('verdict','?'))" 2>/dev/null || echo "?")
        if [ "$verdict" != "APPROVE" ]; then
            echo "  ⚠️  $f → $verdict"
            FOUND=$((FOUND+1))
        fi
    fi
done

# Scan for shell scripts with dangerous commands
for f in $(find "${OLDPWD:-.}" -name "*.sh" 2>/dev/null | head -10); do
    if grep -q "rm -rf\|:(){ :|:& };:" "$f" 2>/dev/null; then
        echo "  🔴 $f → potential danger detected"
        FOUND=$((FOUND+1))
    fi
done

# Check common mistakes in CI configs
for f in $(find "${OLDPWD:-.}" -name "*.yml" -path "*workflow*" 2>/dev/null | head -5); do
    if grep -q "secrets\." "$f" 2>/dev/null; then
        echo "  🔍 $f → uses secrets — ensure allowlist is configured"
        FOUND=$((FOUND+1))
    fi
done

echo ""
if [ $FOUND -eq 0 ]; then
    echo "✅ No risky patterns found."
else
    echo "⚠️  $FOUND potential issues found."
fi

echo ""
echo "Run on your own CI:"
echo "  git clone https://github.com/kittykatemybaby/Agent-lint.git"
echo "  ./agent-lint/agent-lint check \"your action\" --tool sql --rows 100"
echo ""

rm -rf "$TMPDIR"
