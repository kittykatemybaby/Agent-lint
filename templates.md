# Industry Safety Templates

Pre-built safety rules. Copy the ones you need into your agent configuration.

## E-commerce

```json
{
  "refund_bulk": {
    "tool": "sql",
    "pattern": "UPDATE.*refund|DELETE.*order",
    "max_rows": 50,
    "require_approval": true,
    "reason": "Bulk refunds are irreversible and high-impact"
  },
  "pricing_change": {
    "tool": "sql",
    "pattern": "UPDATE.*price|UPDATE.*discount",
    "max_rows": 100,
    "require_approval": true,
    "reason": "Pricing changes affect revenue directly"
  },
  "inventory_write": {
    "tool": "sql",
    "pattern": "UPDATE.*inventory|UPDATE.*stock",
    "max_rows": 500,
    "require_approval": false
  }
}
```

## Fintech

```json
{
  "payment_write": {
    "tool": "sql",
    "pattern": "UPDATE.*balance|INSERT.*transaction|DELETE.*payment",
    "max_rows": 1,
    "require_approval": true,
    "reason": "Financial transactions must be individually verified"
  },
  "account_freeze": {
    "tool": "sql",
    "pattern": "UPDATE.*status.*frozen|UPDATE.*blocked",
    "max_rows": 1,
    "require_approval": true,
    "reason": "Account status changes have legal implications"
  },
  "reporting_read": {
    "tool": "sql",
    "pattern": "SELECT.*SUM|SELECT.*COUNT",
    "max_rows": 10000,
    "require_approval": false,
    "reason": "Read-only reporting is safe at scale"
  }
}
```

## SaaS

```json
{
  "user_delete": {
    "tool": "sql",
    "pattern": "DELETE.*user|DELETE.*account",
    "max_rows": 1,
    "require_approval": true,
    "reason": "User deletion is irreversible and triggers GDPR obligations"
  },
  "subscription_cancel": {
    "tool": "sql",
    "pattern": "UPDATE.*subscription.*cancel|DELETE.*subscription",
    "max_rows": 10,
    "require_approval": true,
    "reason": "Subscription changes affect MRR"
  },
  "analytics_query": {
    "tool": "sql",
    "pattern": "SELECT.*analytics|SELECT.*metrics",
    "max_rows": 50000,
    "require_approval": false,
    "reason": "Analytics queries are read-only and expected to be large"
  },
  "api_rate_limit": {
    "tool": "http_post",
    "pattern": "api.*bulk|api.*batch",
    "max_impact": 100,
    "require_approval": false,
    "risk_bump": 0.2
  }
}
```

## Usage

```bash
agent-lint check "UPDATE orders SET status='refunded'" --tool sql --rows 200
# With E-commerce template loaded → REJECT (refund_bulk: max 50 rows)
```

Add templates to your agent-lint config directory. The engine matches patterns against action descriptions and applies per-template rules.
