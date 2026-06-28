# Project Brain 迭代路線

2026-06-28 · v0.1 → v1.0

---

## 現狀 (v0.1) — 已建成

```
✅ SQLite persistent store (5 record types)
✅ 關鍵字相似度檢索 + recency decay
✅ Auto-compression (≥3次同類 → pattern)
✅ Critic structured signal (6 heuristic checks)
✅ Cognitive isolation (Builder 不讀 critic reasoning)
✅ Pre-seeded (5 failures + 4 constraints)
✅ Builder context shrink (last decision + top 3 failures only)
```

**弱點：** 關鍵字匹配粗糙。無自動事件記錄。無跨 session 持久化。

---

## Phase 1：Search & Embedding (1–2 天)

```
關鍵字相似度 → embedding-based semantic search
```

| 項目 | 做法 |
|------|------|
| **DeepSeek embeddings** | 用現有 API key，batch embed，存 SQLite BLOB |
| **Hybrid retrieval** | dense(0.5) + sparse(BM25,0.3) + recency(0.2) |
| **Background re-index** | cron 定時重建 embedding index |
| **Top-K + threshold** | 只返回 similarity > 0.3 的結果 |

**風險：** DeepSeek embeddings API 成本。batch mode 省 50%。

---

## Phase 2：Auto-logging & Tagging (2–3 天)

```
手動 record_failure() → 自動 event logging
```

| 項目 | 做法 |
|------|------|
| **Event hook** | 在 pipeline_graph 每個 node 前後自動 log |
| **Auto-tagging** | timeout / wrong_tool / auth_failure / silent_failure 自動分類 |
| **Failure fingerprint** | trace_id + error_pattern → 同類歸併 |
| **Reusability auto-calc** | fix 成功率 → reusability 自動更新 |

```
raw log → auto-tag → cluster → abstract pattern → gene_map seed
```

**與 gene_map 整合：** project_brain 養出 pattern → 自動寫入 gene_map。

---

## Phase 3：Experiment Engine (3–5 天)

```
「試了 X，結果 Y」→ 結構化追蹤
```

| 項目 | 做法 |
|------|------|
| **Experiment record** | what_we_tried, hypothesis, result, learned |
| **A/B style** | 兩個方案 → 執行 → 比較 outcome → 記錄 |
| **Cross-reference** | experiment → resulting failures/decisions 自動關聯 |

**例子：**
```json
{
  "type": "experiment",
  "context": "Try headless OAuth via playwright vs xurl CLI",
  "hypothesis": "playwright can complete OAuth without user",
  "result": "failed — Google blocks automated browser OAuth",
  "learned": "OAuth requires user's phone for Google/X. Use bearer token for reads."
}
```

---

## Phase 4：跨 Session & 協作 (5–7 天)

```
單一 session → 跨重啟持久化
```

| 項目 | 做法 |
|------|------|
| **Session boundary** | Hermes 重啟時自動 save/restore hot context |
| **Context snapshot** | 重啟前 snapshot current task + plan → working memory |
| **Multi-agent brain** | 多個 subagent 共享同一個 project_brain.db（read-only for subagents） |
| **Obsidian sync** | 每日自動 export top patterns/decisions → vault |

---

## 優先級

| 優先 | 階段 | 原因 |
|------|------|------|
| 🔴 現在 | Phase 1 (Embedding) | 關鍵字匹配太粗糙，高價值決策需要準確檢索 |
| 🟠 下週 | Phase 2 (Auto-logging) | 解放手動記錄，數據飛輪開始轉 |
| 🟡 兩週 | Phase 3 (Experiment) | 支持 A/B 測試文化 |
| 🟢 以後 | Phase 4 (跨 Session) | 目前重啟少，尚不急 |

---

## 不做的事

- ❌ 不引入外部向量資料庫（Pinecone/Weaviate）—— 成本 + 依賴
- ❌ 不做 real-time embedding update —— batch 就夠
- ❌ 不做 full-text search engine —— SQLite FTS5 已夠用
- ❌ 不取代 gene_map —— project_brain 是長期記憶，gene_map 是熱路徑快取，互補
