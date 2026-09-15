# Codebase Concerns

**Analysis Date:** 2026-09-02

## Workspace Framing

`C:\Users\Davis` is a Windows 11 **home-directory workspace** (not a git repo) holding several independent source-code projects interleaved with OS profile internals. This audit covers the four mapped projects plus inert directories:

| # | Project | Root | Nature | Authored locally? |
|---|---------|------|--------|-------------------|
| 1 | 主升浪 "gogo" (main-wave) | `Desktop/项目/gogo` | Live-traded A-share limit-up decision system, Python, 27.5k LOC across 116 `.py` files, 181 commits | Yes — primary |
| 2 | vibe-astock | `vibe-astock` | A-share short-term review dashboard (LangGraph + FastAPI + React, duanxian/), 46 `.py` files | No — shallow clone (1 commit, author PaulX1029, remote `simonlin1212/vibe-astock`), clean tree |
| 3 | HiThink-Financial-API | `HiThink-Financial-API` | Official 同花顺 data service (Python SDK + Node CLI) | No — clean checkout, 0 divergence from `origin/main` |
| 4 | UZI-Skill | `UZI-Skill` | Stock deep-analysis agent skill plugin | No — clean checkout, 0 divergence from `origin/main` |

Inert/non-code (checked, excluded): `PSAppDeployToolkit/` (empty `ExecuteAsUser/`), `abu/` (data/log only), `ansel/` (empty), `chrome_test/` + `chrome_ticket_debug/` (Chrome profile dirs), `Desktop/K/` (3,049 Sohu hisHq JSON files, data cache), `Desktop/bazi/` (2 standalone scripts), OS internals (`AppData/`, `NTUSER.DAT*`, `WPS Cloud Files/`, `iCloudDrive/`, `node_modules/`). The `.planning/codebase/` documents from previous mapping runs (`STACK.md`, `ARCHITECTURE.md`, etc.) cover the same 4 projects.

Both gogo and vibe-astock checkouts are **shallow clones** (`.git/shallow` present). gogo's shallow boundary predates 2026-08-31 (historical commits below are reachable locally).

## Top Concerns (priority order)

1. **Repository exposure**: `github.com/valdislaul-dot/main-wave` answered an anonymous HTTP fetch with **200** on 2026-09-02 (GitHub serves 404 for private repos) — yet `STACK.md` (prior map) states the repo is *private*. If public, the strategy codebase AND historical trading records are exposed (see Security).
2. **Trading account records exist in pushed git history** of gogo (positions, P&L, journal) — the 2026-08-31 gitignore/removal commit does not erase history.
3. **Zero automated tests** in the live-traded gogo system (27.5k LOC, no test files).
4. **Repository-as-database bloat**: 493 tracked JSON files, 603 MB pack, 2.0 GB working tree — auto-commit+push every trading day.
5. **Silent-failure culture**: 119 broad `except` handlers; several bare `except: pass` swallowing pipeline steps.
6. **Uncommitted in-progress pipeline change** (run_pipeline.py Step 8.6 importing an untracked module) — fragile against the Mac/Win dual-machine sync model.
7. **Data-source parser duplication**: one Tencent fqkline endpoint parsed independently in 5+ files; a schema bug was fixed in only 2 of them (commit `a8514d5`).

---

## Tech Debt

### gogo: experiment-script sprawl (no cleanup discipline)
- Issue: 70 one-off Python scripts kept at `Desktop/项目/gogo/scripts/` root alongside the 40-file production pipeline in `scripts/daily/` — research leftovers like `scripts/final_strategy_analysis.py`, `scripts/deep_strategy_analysis.py`, `scripts/strategy_analysis.py`, `scripts/final_grid_search.py`, `scripts/exhaustive_search.py`, `scripts/calibrate_v2.py`, `scripts/calibrate_v3.py`, `scripts/calibrate_execution.py`, `scripts/optimized_model.py`, `scripts/filter_optimization.py` (each 400–560 lines) plus `scripts/backup/legacy_scripts/` (6 more) and `backup/auction_backup_20260827.zip`.
- Impact: readers/agents cannot tell production from archaeology; naming collisions across generations (`backtest_v2.py` at root vs `backtest_v4.py` + `backtest_v4_long.py` in daily); stale calibrate scripts imply config drift risk vs `data/scoring_config.json`.
- Fix approach: move non-production scripts to `backup/research/<date>/`, keep `scripts/daily/` as the only executable path, add a README index.

### gogo: repository used as a database
- Issue: `sync_cloud.py` (in `scripts/daily/`) auto-commits and auto-pushes JSON snapshots every pipeline run (`[auto] 数据快照同步` commits daily). Tracked: 493 JSON files including `data/backtest_kline/*.json` (70 files, ~410 KB each), `data/zt_pool/*.json` (25 dated daily pools), `data/stock_data.json` (2.4 MB), `data/historical_zt_pool.json` (churns ~500 lines per sync).
- Impact: `git count-objects` shows a 603 MB pack over 181 commits; pushes grow slower; daily snapshots permanently dirty the tree; `data/zt_pool/20260902.json` style files stay untracked unless manually added (inconsistent capture — see Fragile Areas).
- Fix approach: move `data/backtest_kline/` and dated pool dumps into a gitignored data store (as already done for `data/kline_data/`); keep only state files (`*_state.json`) in git.

### gogo: broad exception swallowing
- Issue: 119 `except Exception`/bare handlers across `scripts/daily/*.py`; e.g. `scripts/daily/run_pipeline.py:155,170` (`except: pass`), `scripts/daily/zt_pool.py:141,188`, `scripts/daily/scoring.py:391,413`, `scripts/daily/sell_engine.py:235`, `scripts/daily/screen_candidates.py:192`, `scripts/daily/active_pool.py:29,33`.
- Impact: deliberate resilience (scraper fallbacks) but failures degrade silently — a failed capture prints `[Warning]` and the pipeline continues with stale/absent data, which then feeds reports and the auction panel (contradicts the project's own 数据引用纪律).
- Fix approach: log-with-context (`logger.warning(..., exc_info=True)` or re-raise after marking step failed in `data/*_state.json`) so the daily status surface shows degraded steps instead of only stdout.

### vibe-astock: two parallel applications in one repo
- Issue: live entry `server.py` (FastAPI over `duanxian/`, imports `main.py`) coexists with a legacy second app `vr/app.py` (also FastAPI, flat imports of `vr/astock.py`, `vr/chat.py`, `vr/gstock.py`, `vr/watchtower.py` etc., runnable only from `vr/` cwd).
- Impact: `tests/test_core_logic.py:1806-1807` explicitly guards against `vr.app` being imported into the server process ("后台调度线程会翻倍") — the two schedulers would double-run if wiring is ever confused; deploy docs must keep pointing at `server.py`.
- Fix approach: delete `vr/` or move under `legacy/` with a tombstone README, after confirming nothing production-side launches it.

### vibe-astock: monolith test file
- Issue: all 4,433 lines of tests live in one file `vibe-astock/tests/test_core_logic.py`.
- Impact: test runs serialize fine but triage/filtering (`-k`) gets slow and diff review of tests is coarse-grained.
- Fix approach: split per class (`test_session.py`, `test_verification.py`, `test_stats_context.py`, ...) mirroring existing class boundaries.

## Known Bugs

### Tencent fqkline `day`-key absence — bug class only partially fixed
- Symptoms: codes whose 腾讯 fqkline payload lacks the `day` key (e.g. non-除权 stocks) crash or return empty klines; previously caused a `name_code` misreport (京蓝科技).
- Files: fixed in `scripts/daily/update_data.py:55` and `scripts/daily/backfill_kline_fields.py:60` (commit `a8514d5`, "腾讯fqkline无除权股day键回退"); **the same endpoint is parsed independently and unverified** in `scripts/daily/fetch_backtest_klines.py:44`, `scripts/daily/backtest_divergence.py:30`, `scripts/daily/review_recommendations.py:108`, and `scripts/daily/morning_check.py:66` (different payload shape).
- Trigger: backtest/review paths hitting non-除权 codes (600/601 banks etc.).
- Workaround: none in the unpatched files — verify each parser handles a missing `day` key.
- Fix approach: extract one shared kline-fetch/parse module (`scripts/daily/kline_source.py` already centralizes Tushare vs Tencent choice for the daily path) and route all five call sites through it.

## Security Considerations

### gogo GitHub repository appears to be PUBLIC and history contains trading account records
- Risk: anonymous fetch of `https://github.com/valdislaul-dot/main-wave` returned HTTP 200 on 2026-09-02 (private repos return 404). Prior `STACK.md` claims "private" — one of the two is wrong; **verify immediately**: `gh repo view valdislaul-dot/main-wave --json visibility,isPrivate`.
- Compounding: git history (still reachable on `main`, shallow boundary predates it) contains real accounting commits pushed before the 2026-08-31 hygiene fix:
  - `d11d116` "账目: 08-31三笔+提现(湖南黄金清仓-2,998模型19笔; 金牛/沃特买入模型账; 提现1,000)" — touched `logs/portfolio.json`, `logs/trading_journal.json`, `logs/daily_reports/2026-08-31.md` (positions, realized P&L, withdrawals).
  - `0bad0b3` — touched `CLAUDE.md`, `.gitignore`, `logs/daily_reports/2026-08-31.md`.
  - Removal commit `f65c5bf` ("持仓/账目/日志与项目说明不上传GitHub") only untracked these files; **it does not remove them from history**.
- Current mitigation: files gitignored since 2026-08-31; `sync_cloud.py` whitelist pushes market data only; `CLAUDE.md`/`CONTEXT.md`/`memory/`/`logs/` gitignored.
- Recommendations: (1) confirm visibility; if public, set private immediately — daily auto-push (`run_pipeline.py` Step 9 → `sync_cloud.py` commit+push) re-exposes state every trading day; (2) purge history (BFG / `git filter-repo`) of `logs/`, `CLAUDE.md`, `data/*.xlsx` and coordinate a force-push/clean-clone with the Mac-side clone (multi-end workflow makes this a planned, user-approved operation); (3) rotate the Tushare/HiThink tokens afterward as belt-and-braces.

### Plaintext API tokens at rest
- Risk: `data/tushare_token.txt` and `data/hithink_token.txt` hold API keys in plaintext on disk (gogo). Never tracked in git (verified: absent from `git ls-files` and history) — exposure only via local compromise/backup, or a future `git add .`.
- Mitigation: `.gitignore` entries exist (`Desktop/项目/gogo/.gitignore`); `scripts/daily/kline_source.py:26` reads token from env var first, file second.
- Recommendation: prefer env vars; at minimum keep the gitignore lines and never whitelist them in `sync_cloud.py`.

### Cleartext HTTP to market-data endpoints
- Risk: quote/kline calls use plain `http://` — `scripts/daily/morning_check.py:66` (`http://qt.gtimg.cn`), `scripts/daily/update_data.py:55`, `scripts/daily/fetch_backtest_klines.py:44`, `scripts/daily/backtest_divergence.py:30`, `scripts/daily/review_recommendations.py:108` (`http://web.ifzq.gtimg.cn`). A MITM/proxy could alter prices that feed buy/sell decisions; network errors are already a top failure mode.
- Current mitigation: none (Sina fallback in `morning_check.py` uses `https://hq.sinajs.cn`).
- Recommendation: switch to `https://` variants (both Tencent hosts serve HTTPS); low effort, removes a decision-data integrity hole.

### Positive patterns (no action)
- vibe-astock: credentials live outside the repo in `~/.config/mimo/mimo.env` (`duanxian/config.py`); only `.env.example` is committed; no bare-except handlers found; its test suite hard-blocks outbound network (`tests/conftest.py`).
- HiThink-Financial-API and UZI-Skill checkouts are clean upstream snapshots (verified 0/0 divergence) — no local secret material found.

## Performance Bottlenecks

### gogo git operations (repo bloat)
- Problem: 603 MB pack, 2.0 GB working tree (`Desktop/项目/gogo/`), dominated by tracked JSON history; largest tracked files are `data/backtest_kline/*.json` (~410 KB each, 70 files) and `data/stock_data.json` (2.4 MB).
- Cause: daily `[auto] 数据快照同步` commits of whitelisted state files since 2026-08-16; earlier bulk commits of kline JSONs.
- Impact: GitHub soft-limits warn past 1 GB; every pipeline Step-9 push grows; the Mac↔Win sync (both ends run pipelines against the same origin) gets slower and more conflict-prone; shallow-clone boundary on both machines hides part of the cost but not the push side.
- Improvement path: untrack `data/backtest_kline/` (regenerate from `data/kline_data/`), stop committing dated pool dumps, then run `git gc`/`filter-repo` only if history shrink is needed (see Security — a scrub may be warranted anyway).

### gogo scraping loops (auction SLA risk)
- Problem: full-scan fetches apply per-request sleeps: `scripts/daily/update_data.py:338,347` (0.05/0.03 s), `scripts/daily/auction_pool.py:103,142` (0.1 s + jitter), `scripts/daily/zt_pool.py:228,303`, `scripts/daily/capture_tboard_minute.py:214,239` — hundreds of sequential HTTP calls.
- Impact: the auction panel must conclude inside the 9:15–9:35 window (`morning_check.py` quick mode, snapshot freshness <3 min is a hard rule); any upstream slowdown pushes the pipeline past open.
- Improvement path: parallelize independent quote fetches (ThreadPoolExecutor) while preserving total rate; measure step durations per run into the state file so SLA regressions are visible.

## Fragile Areas

### gogo `scripts/daily/morning_check.py` (852-line auction-panel monolith)
- Files: `Desktop/项目/gogo/scripts/daily/morning_check.py`
- Why fragile: single file owns candidate loading (`load_latest_candidates` sorts by filename date string — breaks if filename format changes), portfolio load, live-quote dual-source fetch, decision display and the 60-second SLA; fetch failures degrade to `None` and callers must remember to handle it; the global rule "买入开关关闭时也列可买前三并标注仅参考" and quick-mode logic live here and in `run_pipeline.py` interplay.
- Safe modification: add pure helpers + unit tests first (see Test Coverage Gaps); keep display logic out of fetch logic.
- Test coverage: none.

### gogo uncommitted in-flight change (cross-machine hazard)
- Files: `Desktop/项目/gogo/scripts/daily/run_pipeline.py` (modified, uncommitted — adds Step 8.6 importing `backtest_sell_exit.watch_summary`), `Desktop/项目/gogo/scripts/daily/backtest_sell_exit.py` (untracked), `data/historical_zt_pool.json` (modified, uncommitted — not in `sync_cloud.py` whitelist so auto-commit never picks it up), `data/zt_pool/20260902.json` (untracked).
- Why fragile: gogo is a two-machine system (Mac + Win share one origin; user rule = review Mac fixes before applying). If the Win side pulls/rebases or the Mac auto-pushes before these files are committed, Step 8.6's import fails at runtime or the module silently diverges between machines. The dirty `historical_zt_pool.json` also means the "git" tree never reflects truth.
- Safe modification: commit the code change + new module together (single logical change), decide whether pool dumps belong in git at all, and keep `sync_cloud.py` whitelist explicit.

### gogo duplicated rate-limit + wait helpers
- Files: identical `wait>0: sleep(wait + uniform(0.1,0.5))` helper re-implemented in `scripts/daily/screen_candidates.py:29`, `scripts/daily/zt_pool.py:249`, `scripts/daily/fetch_historical_zt_pools.py:30`.
- Why fragile: adjusting backoff policy (e.g. after a block) requires touching every scraper; a fix in one file silently misses the others.

### gogo data-source single points
- Files: `scripts/daily/kline_source.py` (Tushare token + Tencent/Tushare fallback ladder), `scripts/daily/hithink_api.py` (hosted `https://fuyao.aicubes.cn`, token in `data/hithink_token.txt`) — HiThink integration is only days old (2026-08-31) and is the designated zt-pool fallback + double-source validator; `scripts/daily/zt_pool.py` scrapes 同花顺/东财.
- Why fragile: vendor schema drift (see Known Bugs) and rate-limit blocks recur; the fallback chain's health is only as good as the last step's silent `except`.
- Test coverage: none for fallback selection logic.

### vibe-astock vr/ legacy app
- Files: `vibe-astock/vr/` (13 modules) vs live `vibe-astock/duanxian/`.
- Why fragile: tests enforce non-import (`tests/test_core_logic.py:1806`), but nothing stops a stale launch script from starting `vr/app.py` (double scheduler threads). No local ownership — this is a shallow upstream clone (1 commit), so no local git safety net for edits.

## Scaling Limits

- **gogo disk growth**: `data/kline_data/` already 1.3 GB (gitignored — OK) and `Desktop/项目/gogo/` totals 2.0 GB; `data/daily_close/` snapshots accumulate daily. Watch for disk exhaustion on the Win box; `data/zt_pool_history/` (2.6 MB, gitignored) fine.
- **Tracked JSON churn**: `data/historical_zt_pool.json` alone churns ~500 lines/sync in the pack; 181-commit history at 603 MB → ~3.3 MB/commit average. Crossing GitHub's 1 GB soft limit slows pushes for both machines.
- **GitHub repo visibility/size interaction**: if made private, size limits still apply (5 GB hard block) — the 603 MB pack is sustainable, but at current growth rates (~few MB/day snapshots) it will not stay that way indefinitely.

## Dependencies at Risk

- **Unpinned requirements** (`Desktop/项目/gogo/requirements.txt`): `akshare>=1.10.0`, `requests>=2.28.0`, `streamlit>=1.28.0`, `tushare>=1.2.0` — no lockfile. Two machines (Mac/Win) installing at different dates can silently run different scraping/API behavior; akshare especially churns against source sites.
- **Tencent/Sina unofficial endpoints**: no contract; recurring schema bugs (see Known Bugs) and rate blocks. Primary kline + live-quote dependency for the entire pipeline.
- **Tushare**: token-gated official API used for kline fallback (`scripts/daily/kline_source.py`); service/credit changes affect backfill quality.
- **HiThink hosted API** (`fuyao.aicubes.cn`, via `scripts/daily/hithink_api.py`): new (2026-08-31), used as zt-pool fallback + dual-source validator; availability/rate limits unknown long-term; the local `HiThink-Financial-API` checkout is the official mirror for contract reference.
- **Upstream checkouts on this machine**: `HiThink-Financial-API`, `UZI-Skill`, `vibe-astock` are all sync-clean shallow/full clones; they drift the moment upstream moves and are re-fetched — no local modifications, so nothing breaks locally, but gogo's docs/code reference HiThink's API contract (header `X-api-key`, `fuyao.aicubes.cn` in `hithink_api.py`) — keep the checkout refreshed when that contract changes.

## Missing Critical Features

- **No automated tests in gogo** — see Test Coverage Gaps.
- **No per-step success/failure state in the daily pipeline**: steps log to stdout/logs but nothing machine-readable records "Step N degraded today"; the GUI (`scripts/daily/gui_dashboard.py`, `gui_cloud.py`) and report (`scripts/daily/generate_report.py`) trust JSON snapshots regardless of capture health. A capture-health field in `data/market_state.json`/`data/auction_state.json` would make the daily surface honest.
- **No schema validation** on captured snapshots (`data/auction/*.json`, pool files): downstream consumers assume key shapes; a source change corrupts reports rather than failing loudly.
- **No alerting** — the pipeline is silent until the user opens the panel; a 9:25 auction capture failure discovered at 9:30 is unrecoverable for that day.

## Test Coverage Gaps

### gogo — CRITICAL: zero tests for live-traded logic
- What's not tested: everything — scoring (`scripts/daily/scoring.py:296 compute_score`, `classify_volume`, `seal_quality`), sell engine (`scripts/daily/sell_engine.py:245 sell_signal`, `:503 sell_execution_price`, `:572 check_vwap_breach`), zt-pool state machine (`scripts/daily/zt_pool.py`), auction decision, portfolio/exit log mechanics. No `test_*.py` file exists in the repo (verified).
- Files: `Desktop/项目/gogo/scripts/` (27.5k LOC).
- Risk: every recalibration ("9月权重重搜", V4 rules), sell-engine tweak, or parser fix ships without regression safety; the 181-commit history is full of "fix/三连修/双修" commits — each fixing something a test would have caught (e.g. 赚钱效应恒0三连修 `d1a8f7b`/`f45b236`).
- Priority: High. Suggested first targets: `sell_engine.sell_signal`/`check_vwap_breach` (pure functions over kline arrays — trivially unit-testable with fixtures from `data/backtest_kline/`), then `scoring.compute_score`, mirroring the disciplined pattern already proven in `vibe-astock/tests/` (network-blocking autouse fixture, pure-logic-only policy).

### vibe-astock
- What's not tested: any real-data integration path — `pytest.ini` declares an `integration` marker but zero integration tests exist; the 4,433-line `tests/test_core_logic.py` covers pure logic only (408 mock/patch usages). Frontend: 32 `.ts/.tsx` files under `frontend/src/` with no test setup in `frontend/package.json`.
- Risk: fetcher/LLM-call refactors (e.g. `duanxian/fetchers.py`, 628 lines) are protected only by mocked tests; degradation against real 腾讯/Sina responses passes CI.
- Priority: Medium.

### HiThink-Financial-API / UZI-Skill
- Upstream projects with their own CI (`HiThink-Financial-API/.github/workflows/`); local checkouts contribute nothing — no gap locally.

---

## Appendix: Evidence Notes

- Repo visibility test: `curl -o /dev/null -w "%{http_code}" https://github.com/valdislaul-dot/main-wave` → 200 on 2026-09-02 (control repo returned 200; private repos return 404). GitHub API was rate-limited, so confirm via `gh repo view`.
- Git pack size: `git count-objects -vH` in `Desktop/项目/gogo` → size-pack 603.44 MiB, 552 objects.
- Broad-except count: `grep -c "except Exception\|except:" scripts/daily/*.py` → 119.
- Sensitive-history commits: `d11d116` (logs/portfolio.json, logs/trading_journal.json, logs/daily_reports/2026-08-31.md), `0bad0b3` (CLAUDE.md, .gitignore, daily report), removal `f65c5bf`.
- Untracked/dirty at audit time (2026-09-02): `scripts/daily/run_pipeline.py`, `scripts/daily/backtest_sell_exit.py`, `data/historical_zt_pool.json`, `data/zt_pool/20260902.json`.

---

*Concerns audit: 2026-09-02*
