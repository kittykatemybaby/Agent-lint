# agent-lint vs 競品技術差異

2026-07-01

## 直接競爭：Aegis (Justin0504/Aegis) ⭐360

| 維度 | Aegis | agent-lint | 差異 |
|------|-------|-----------|------|
| **定位** | Desktop app firewall | CLI tool | Aegis 有 GUI，我們沒有 |
| **語言** | TypeScript | Python | 不同生態 |
| **分發** | npm + PyPI + Docker + macOS .dmg | git clone only | Aegis 領先 10x |
| **成熟度** | 360 stars, 4 months old | 0 stars, 1 week old | Aegis 早我們 4 個月 |
| **Runtime** | Real-time intercept (runtime proxy) | Pre-execution check (CLI) | Aegis 攔截 runtime；我們檢查 deploy 前 |
| **審計** | 加密審計追蹤 | research_audit.py (SQLite) | 相近 |
| **人機迴圈** | 內建 approval UI | 僅 CLI 輸出 | Aegis 領先 |
| **Kill switch** | 有 | 無 | Aegis 獨有 |
| **零程式碼變更** | 聲稱支援 | git clone 後需手動配置 | Aegis 更方便 |
| **基因記憶** | 無 | gene_map.py (1ms 熱命中) | **我們獨有** |
| **跨模型審計** | 無 | critic_gate.py | **我們獨有** |
| **盲預測+對賬** | 無 | prediction_dataset.py | **我們獨有** |
| **記憶驗證** | 無 | memory_verify.py (狀態機) | **我們獨有** |
| **壓縮引擎** | 無 | aggressive_compress.py (v2) | **我們獨有** |
| **Replay** | 部分（審計追蹤） | replay_engine.py | 相近 |
| **Story Mode** | 無 | story_mode.py | **我們獨有** |
| **Cost Analytics** | 無 | cost_analytics.py | **我們獨有** |
| **授權** | MIT | MIT | 相同 |
| **價格** | 開源，有商業頁面 | 開源，無價格 | Aegis 已有商業化意圖 |

## 新發現的競爭者

| 產品 | 星 | 做什麼 | 我們的差異 |
|------|-----|--------|-----------|
| **pinecone-io/cultivar** | 26 | Agent Skills 沙盒測試 | Pinecone 背書，但專注 skills 而非 actions |
| **Trajeckt** | 2 (HN) | Firewall for AI agents | 太新，未驗證 |
| **ECP** | 1 (HN) | Evaluation Context Protocol | 協議標準，不是產品 |
| **Valmis** | 3 (HN) | OpenClaw alternative with security | 替代品，非專注 agent 安全 |

## 市場成熟度判斷

Aegis 360 星 + macOS app + npm + Docker = 市場正在升溫，不是我們的幻想。但 Aegis 做 **runtime proxy**（攔截正在執行的 agent），我們做 **pre-deploy CLI**（部署前檢查）。

互補，不是完全競爭。他們適合「我 agent 正在跑，萬一出事要攔住」。我們適合「我 agent 還沒部署，先檢查會不會出事」。

## 行動建議

1. **別跟 Aegis 拼 GUI**——我們沒前端能力。走 CLI-first 差異化。
2. **強調我們獨有的 6 個模組**——gene map, critic gate, blind prediction, memory verify, compression, story mode。Aegis 沒有這些。
3. **README 加入對比表**——明確告訴開發者「什麼時候用 agent-lint，什麼時候用 Aegis」
