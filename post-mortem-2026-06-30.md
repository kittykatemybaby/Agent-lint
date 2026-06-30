# Post-Mortem: Telegram Gateway Instability

2026-06-30 · Kitty Kate

---

## Incident

Telegram 端出現 TimedOut / Bad Gateway。

## Root Cause

Cron jobs 有不健康的執行模式：

1. **sqlite3 CLI 不存在** — Brain backup 使用 `sqlite3` 指令，但 VPS 未安裝，每次執行報錯
2. **前景 & 背景化** — Landing auto-restart 用 `python3 -m http.server &`，在 foreground mode 中觸發警告
3. **健康檢查太弱** — Landing 用 `pgrep` 檢查，不確認實際 HTTP 200 回應

這些不健康的 tool 呼叫可能在 cron 執行時影響 gateway 穩定性。

## Fixes Applied

| 問題 | 修復 |
|------|------|
| sqlite3 CLI 不存在 | 改用 Python `sqlite3` 模組 |
| `&` 背景化 | 移除，改用 `nohup` |
| pgrep 健康檢查 | 改用 `curl -sI` 確認 200 |
| 每次失敗即重啟 | 改為連續 3 次失敗才重啟 |
| 綁定 0.0.0.0 | 改為 `--bind 127.0.0.1` |

## New Constraints (enforced in project_brain)

1. 所有 cron job 只能用 Python — 禁止 sqlite3/psql 等系統 CLI
2. 禁止在 foreground terminal 中使用 `&`
3. 健康檢查必須驗證實際回應（curl），不是只看 process 存在

## Prevention

- 每週審計 cron jobs.json 是否有健康問題
- 新 cron job 創建前必須過 critic_gate
- Gateway 異常時優先檢查最近 cron 執行記錄
