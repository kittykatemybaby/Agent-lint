# agent-lint

[![CI](https://github.com/kittykatemybaby/Agent-lint/actions/workflows/ci.yml/badge.svg)](https://github.com/kittykatemybaby/Agent-lint/actions)
[![MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`agent-lint` 在 agent 執行前檢查其動作和 trace。使用啟發式規則找出高風險輸入和異常執行路徑——執行時不調用 LLM。

---

## 解決什麼問題

部署會調用工具（SQL、HTTP、email）的 AI agent 而不加護欄，會出現兩種失敗：

1. **無聲破壞。** agent 對 50,000 行執行了 `UPDATE orders SET status='refunded'`。你從憤怒的客戶那裡才發現。
2. **重複犯錯。** 同樣的錯誤模式每次 session 都出現。每次從零診斷，燒 token 也燒時間。

`agent-lint` 加上執行前檢查和錯誤記憶，讓這些問題提早被攔截。

---

## 怎麼用

### 檢查一個動作

```bash
$ agent-lint check "DELETE FROM orders WHERE status = 'pending'" --tool sql --rows 5000
{
  "verdict": "REJECT",
  "risk_score": 0.70,
  "patterns_detected": ["影響範圍 (5000) 超過上限 (1000)"]
}
```

工具將動作與已註冊的規範比對（最大行數、可逆性、已知風險模式）。不涉及 LLM。

### 檢查一個安全的動作

```bash
$ agent-lint check "SELECT * FROM orders WHERE created > '2026-01-01'" --tool sql --rows 100
{
  "verdict": "APPROVE",
  "risk_score": 0.30,
  "patterns_detected": []
}
```

### 顯示已知錯誤模式

```bash
$ agent-lint genes
DeepSeek API timeout      → retry (延遲: 3s, 最多 2 次)
Rate limit 429             → backoff (延遲: 60s)
Database connection refused → retry (延遲: 5s, 最多 2 次)
Permission denied          → escalate (需人工介入)
```

### 審計 trace 檔案

```bash
$ agent-lint audit trace.json
{
  "steps": 12,
  "errors": 1,
  "warnings": 2,
  "findings": [
    {"step": 7, "severity": "error", "description": "POST /refund 超時"},
    {"step": 7, "severity": "warning", "description": "第 7 步耗時 6200ms (偏慢)"}
  ]
}
```

---

## Dashboard（可選）

```bash
python3 dashboard_server.py
# → http://localhost:8765
```

本地 Web 介面，顯示系統狀態、待處理動作、行為漂移視覺化。無需外部服務。

![Dashboard](screenshot.png)

---

## 它不是什麼

- **不是保證。** 風險評分是啟發式的。低分不代表絕對安全，高分不代表一定危險。它是標記工具，不是證明系統。
- **不是即時攔截。** 它在部署前檢查動作，不攔截正在執行的 agent 呼叫（那是 refutability engine 的範疇，後續版本）。
- **不取代人工審核。** 高風險動作的最終決定應由人做出。
- **不是追蹤平台。** 它審計你提供的 trace，不會自動收集。

---

## 評分怎麼算

風險分數由以下因子加權計算：

| 因子 | 權重 | 示例 |
|------|------|------|
| 工具類型基礎風險 | 0.1–0.4 | SQL 寫入比讀取風險高 |
| 影響範圍（受影響行數） | 0–0.3 | 50,000 行 > 100 行 |
| 不可逆性 | +0.1 | DELETE 不可撤回 |
| 已知模式匹配 | +0.15–0.4 | "批量刪除"、"用戶資料存取" |
| 可逆性檢查 | 可逆動作 0 加成 | 檔案寫入可以回滾 |

閾值：
- **≥0.70** → REJECT（拒絕）
- **0.40–0.69** → ESCALATE（升級人工審查）
- **<0.40** → APPROVE（通過）

`--rows` 存在的原因是影響範圍很重要。對 5 行執行 `DELETE` 和對 50,000 行完全不同。工具需要知道爆炸半徑。

---

## 模組

| 模組 | 用途 |
|------|------|
| `stop_conditions.py` | 為每個 pipeline 步驟定義成功條件和停止條件 |
| `gene_map.py` | SQLite 錯誤記憶——儲存已知錯誤→修復對應，1ms 查詢 |
| `prediction_dataset.py` | 行動前盲預測，事後比對實際結果，追蹤準確率 |
| `cross_audit.py` | 讀取 pipeline 輸出，標記訊號品質、卡住的序列、資料缺口 |
| `observation_lifecycle.py` | 提升有效的模式，歸檔無效的模式 |

全部零外部依賴。純 Python 3.10+。

---

## 安裝

```bash
git clone https://github.com/kittykatemybaby/Agent-lint.git
cd Agent-lint
chmod +x agent-lint
bash demo.sh
```

或從 repo 直接 pip 安裝：

```bash
pip install git+https://github.com/kittykatemybaby/Agent-lint.git
```

---

## 限制

- 評分是基於規則的，非自我學習。不更新模式定義就不會自己進步。
- 無內建事件收集。你帶來 trace 給它，它不會接入你的 agent runtime。
- Gene Map 出廠自帶 5 個預設模式。它隨著你記錄修復而成長——空的 Gene Map 毫無價值。
- Cross-audit 讀取本地 JSON 檔案。不連接任何可觀測性平台。
- Dashboard 僅限本地。無驗證、無多租戶。

---

## 真實案例

某金融科技團隊在 CI 中用 `agent-lint` 把關其 AI agent 生成的 SQL：

```yaml
# .github/workflows/agent-check.yml
- name: 檢查 agent 動作
  run: |
    agent-lint check "$(cat agent_output.sql)" --tool sql --rows "$(wc -l < affected.csv)"
    agent-lint audit latest_trace.json
```

如果 agent 對 10,000 行生成了 `DELETE`，CI 會阻止部署。

---

## License

MIT。由 [Kitty Kate](https://x.com/KittyKatemybaby) 打造。

[English](README.md)
