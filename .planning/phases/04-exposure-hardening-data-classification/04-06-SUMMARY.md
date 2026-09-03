---
phase: 04-exposure-hardening-data-classification
plan: 06
subsystem: docs
tags: [sec-02, sc5, data-classification, known-limits, project-doc, readme, docs-only]

# Dependency graph
requires:
  - phase: 04-exposure-hardening-data-classification (04-03)
    provides: "/v1/private/* token-gated namespace + frozen 04-01 envelope codes (409 already_running / 422 shapes) — the implemented facts the README known-limits section cites"
  - phase: 04-exposure-hardening-data-classification (04-04)
    provides: "date whitelist four-gate order (404 kind → 422 invalid_date_format → 422 date_not_supported → 202) — the trigger semantics the README single-flight section must not overclaim beyond"
  - phase: 04-exposure-hardening-data-classification (04-05)
    provides: "boot posture facts the README documents: loopback default 127.0.0.1, non-loopback binds require GOGO_API_TOKEN env (data/api_token.txt file token does NOT satisfy — WR-01/D-12)"
provides:
  - ".planning/PROJECT.md Constraints/Security 数据分级分类表 (定稿): two-tier table (公开级 /health /health/ready /v1/state/* /openapi.json 无需 key | 机密级 /v1/private/* + POST /v1/actions/* + GET /v1/jobs/* X-API-Key 必填) with router-source grep column, 定稿 stamp (2026-09-02 用户确认 + Phase 4 定稿 2026-09-04, 改动需用户明确确认), privacy red-line pointer (2026-08-31), README known-limits pointer — the standing SEC-02 reference for every future endpoint decision"
  - "README.md known-limits section (local-only file): endpoint inventory byte-verified against api/main.py + router decorators, single-flight scope (per-kind 409, envelope codes already_running / already_running_other_entry), residual concurrent entry points honestly listed (Mac crontab 无锁 / 手动 CLI / GUI 弃用 2026-09-04), boot posture, classification pointer; SC5 documented-limits clause satisfied on the local document the 04-07 gate reads"
  - "SC5 scan evidence recorded in this SUMMARY: data/api_token.txt absent from git history, absent from sync_cloud whitelist, .gitignore covers token + logs"
affects: [04-07 (live gate: human-check reviews README content against the running service + records machine-truth of residual entry points), verify-work, phase-05 ops polish]

actuals:
  tokens: 630     # chars/4 over the realized diff: PROJECT.md +1073 chars (committed) + README.md +1448 chars (working tree, local-only — see deviation 1)
  tasks: 2
  commits: 1      # per-task commits; task 2 has no commit by design (README.md gitignored — user 2026-08-31 rule)

tech-stack:
  added: []       # docs-only plan — zero packages, zero code changes
  patterns:
    - "Classification table as standing reference: the table carries its own 定稿 stamp + privacy red-line link + router-source column so a future phase greps table → code instead of reconstructing policy from memory"
    - "Known-limits honesty: README claims exactly what the code implements (per-kind single-flight + two 409 envelope codes byte-checked at api/actions.py raise sites) and names the residual concurrent entry points 04-CONTEXT records — no invented locks/rate-limits/ETags"

key-files:
  created: []
  modified:
    - .planning/PROJECT.md - Constraints/Security 数据分级分类表 (7 lines added: 定稿 line + 2-tier table + router sources)
    - README.md - API 已知限制 section appended (endpoint inventory + single-flight scope + residual entry points + boot posture) — working-tree only, NOT committed (user rule, deviation 1)

key-decisions:
  - "README.md content is written to the local file but NOT committed to git: repo CLAUDE.md + .gitignore (2026-08-31 用户定) keep 项目说明 (README among them) 一律不上传 GitHub, 仅本地 — the plan's task-2 commit step contradicts a standing user rule, CLAUDE.md takes precedence (executor rule); the SC5 documented-limits clause is satisfied on the local document, and the 04-07 gate reads the local file"
  - "README assumption resolution: the file is a stale v2-era strategy doc (71 lines, no API section) — the API known-limits section was created additively before 许可证 instead of inserted into a nonexistent API section"
  - "Single-flight wording scoped to the byte-checked facts: per-kind lock (`job_lock.acquire(kind)`), same-API overlap → already_running + running_job_id, external-entry hold → already_running_other_entry without job_id (api/actions.py raise sites + api/errors.py comment, verified during the task)"

patterns-established:
  - "Byte-truth docs gate: every endpoint string in both deliverables was grep-verified against the route decorators (api/main.py /health + /openapi.json, api/state.py /v1/state/{name} + /health/ready, api/private.py /v1/private/{name}, api/actions.py POST /v1/actions/{kind} + GET /v1/jobs/{job_id}) before the write — the table and README list only served routes"

requirements-completed: [SEC-02]

coverage:
  - id: D1
    description: "PROJECT.md Constraints/Security carries the 定稿-stamped two-tier data classification table (公开级 no-key: /health /health/ready /v1/state/* /openapi.json; 机密级 X-API-Key: /v1/private/* POST /v1/actions/* GET /v1/jobs/*) with router-source column, privacy red-line pointer, README pointer"
    requirement: SEC-02
    verification:
      - kind: other
        ref: "grep route decorators api/main.py api/state.py api/private.py api/actions.py (byte-truth: /v1/state/{name}, /health/ready, /v1/private/{name}, POST /v1/actions/{kind}, GET /v1/jobs/{job_id})"
        status: pass
      - kind: other
        ref: "git show --name-only b8e9169 (exactly '.planning/PROJECT.md')"
        status: pass
      - kind: other
        ref: "grep -c -E 'v1/private|v1/actions|v1/jobs|/health' .planning/PROJECT.md (6 matches)"
        status: pass
      - kind: integration
        ref: "python -m pytest -q (148 passed, 1 skipped)"
        status: pass
    human_judgment: false
  - id: D2
    description: "README.md known-limits section documents single-flight scope (409 already_running + running_job_id; already_running_other_entry), residual concurrent entry points (Mac crontab 无锁/手动 CLI/GUI 弃用), boot posture (loopback default, env-forced GOGO_API_TOKEN for non-loopback), endpoint inventory, classification pointer; SC5 scans pass"
    requirement: SEC-02
    verification:
      - kind: other
        ref: "SC5 scan 1: git log --all --oneline -- data/api_token.txt (empty — token never committed)"
        status: pass
      - kind: other
        ref: "SC5 scan 2: grep -n api_token scripts/daily/sync_cloud.py (no lines — whitelist is data files only)"
        status: pass
      - kind: other
        ref: "SC5 scan 3: grep -n -E 'api_token|logs' .gitignore (L12 data/api_token.txt, L14 logs/*, L27 logs/*.log)"
        status: pass
    human_judgment: true
    rationale: "README.md is a local-only document (gitignored by the user's 2026-08-31 rule) — it cannot be diff-verified through git history; the 04-07 live gate performs the human-check of README content against the running service and records machine-truth of the residual entry points (Mac crontab state is asserted from 04-CONTEXT, not audited from this machine — a docs-task out of scope the gate closes)"

# Metrics
duration: 20min
completed: 2026-09-04
status: complete
---

# Phase 04 Plan 06: Documentation — PROJECT.md 数据分类表 + README known-limits (SC5) Summary

**PROJECT.md Constraints/Security now carries the 定稿-stamped two-tier data-classification table (公开级: /health /health/ready /v1/state/* /openapi.json 无需 key | 机密级: /v1/private/* + POST /v1/actions/* + GET /v1/jobs/* X-API-Key 必填) as the standing SEC-02 reference with router-source grep column and privacy red-line link, and README.md gained a local known-limits section (endpoint inventory, per-kind single-flight 409 scope, residual concurrent entry points, boot posture) — all endpoint strings byte-verified against the route decorators, all three SC5 scans passing with evidence recorded here for the 04-07 gate**

## Performance

- **Duration:** 20 min
- **Started:** 2026-09-04 05:00 (+08:00)
- **Completed:** 2026-09-04 05:20 (+08:00)
- **Tasks:** 2
- **Files modified:** 2 (.planning/PROJECT.md committed; README.md working-tree only — deviation 1)

## Accomplishments

- **PROJECT.md classification table (Task 1, committed `b8e9169`):** Constraints/Security gains the two-tier 数据分级分类表 exactly as the code serves it — 公开级 `/health` `/health/ready` `/v1/state/*` `/openapi.json`（无需 key，无持仓/无策略暴露面）| 机密级 `/v1/private/*`（portfolio/journal/candidates）`POST /v1/actions/*` `GET /v1/jobs/*`（X-API-Key 必填）— with a 路由来源 grep column (api/main.py / api/state.py / api/private.py / api/actions.py), the 定稿 stamp「2026-09-02 用户确认 + Phase 4 定稿 2026-09-04，改动需用户明确确认」, the 隐私红线 (2026-08-31) link, and a pointer to README known-limits. The standing reference future endpoint decisions and reviews read first (SEC-02 documentation requirement).
- **README known-limits section (Task 2, local file):** new「API 服务（gogo-api）— 端点清单与已知限制」section appended before 许可证: byte-verified endpoint inventory table (7 rows, all route decorators grep-checked during the task), single-flight scope (per-kind lock; overlap → 409 `already_running` + `running_job_id`; other-entry hold → `already_running_other_entry` without job_id), the residual concurrent entry points honestly named (Mac 端 crontab 无锁 — 跨机不受本机锁约束 / 手动 CLI / GUI 已弃用 2026-09-04 CLI-only), the boot posture (loopback default; non-loopback requires GOGO_API_TOKEN env — file token does not satisfy, 04-05), the operational rule (定时调度不得与 API 管线触发重叠), and an explicit no-overclaim clause (限流/ETag/304/CORS/全入口互斥 not promised).
- **SC5 scans all pass** (raw outputs in the evidence section below) — token never in git history, never in the sync_cloud whitelist, .gitignore covers token + logs; recorded here for the 04-07 gate, which then needs only the live-service human checks.
- **Docs-only discipline:** no code/test/config changes; full suite green after the edit (148 passed, 1 skipped); `git status --porcelain -- data/ logs/` empty throughout.

## Task Commits

Each task was committed atomically:

1. **Task 1: PROJECT.md 数据分类表 (定稿)** - `b8e9169` (docs; .planning/PROJECT.md +7, specific-path staged; verify gates all passed)
2. **Task 2: README known-limits + SC5 evidence** - *no commit* (see deviation 1: README.md is gitignored by the user's 2026-08-31 standing rule — repo CLAUDE.md takes precedence over the plan's commit step; content delivered to the local file, scan evidence delivered in this SUMMARY)

**Plan metadata:** `docs(04-06): complete plan` (final docs commit with this SUMMARY + STATE/ROADMAP updates)

## Files Created/Modified

- `.planning/PROJECT.md` - modified (+7 lines under Constraints/Security): 定稿 lead line + two-tier table + router sources; committed as b8e9169
- `README.md` - modified (working tree only, NOT committed): new「API 服务（gogo-api）— 端点清单与已知限制」section (~30 lines) inserted before 许可证

## Classification Table Rows (as written in PROJECT.md)

| 数据类别 | 端点 | 保护级别 | 路由来源（grep 起点） |
|----------|------|----------|------------------------|
| 公开级 | `/health`、`/health/ready`、`/v1/state/*`、`/openapi.json` | 无需 key（无持仓/无策略暴露面） | api/main.py、api/state.py |
| 机密级 | `/v1/private/*`（portfolio/journal/candidates）、`POST /v1/actions/*`、`GET /v1/jobs/*` | X-API-Key 必填（持仓/操作/任务状态） | api/private.py、api/actions.py |

定稿 line: 数据分级政策 2026-09-02 用户确认 + Phase 4 定稿 2026-09-04，改动需用户明确确认。隐私红线（2026-08-31）pointer + README「API 已知限制」pointer included.

## README Section Content (as written)

- **端点清单** (7 rows): GET /health · GET /health/ready · GET /v1/state/* · GET /openapi.json（无 key）| GET /v1/private/* · POST /v1/actions/* · GET /v1/jobs/*（X-API-Key）
- **已知限制：单飞锁只约束 API 触发入口**: per-kind single-flight; 409 `already_running` + `running_job_id` (same-API overlap) / `already_running_other_entry` no job_id (other-entry hold); lock covers only POST /v1/actions/* (锁文件 data/locks/, gitignored); residual entry points: Mac crontab 无锁, 手动 CLI, GUI 弃用 (2026-09-04); 操作规则: 定时调度不得与 API 管线触发重叠
- **启动姿态 (2026-09-04 定稿)**: loopback default 127.0.0.1; token 文件 data/api_token.txt 缺失时自动生成 (gitignored); non-loopback requires GOGO_API_TOKEN env — file token does not satisfy (SEC-03/WR-01)
- Explicit no-overclaim sentence (限流/ETag/304/CORS/全入口互斥未实现不承诺)

## SC5 Scan Evidence (raw outputs, Task 2)

- **Scan 1 — token in git history:** `git log --all --oneline -- data/api_token.txt` → *(empty output, PASS — token never committed)*
- **Scan 2 — sync_cloud whitelist:** `grep -n "api_token" scripts/daily/sync_cloud.py` → *(no output lines, PASS — whitelist L29-36 is data/*.json + data/auction/*.json only)*
- **Scan 3 — .gitignore coverage:** `grep -n -E "api_token|logs" .gitignore` → `12:data/api_token.txt`, `14:logs/*`, `27:logs/*.log` *(PASS — token and logs covered)*
- Hygiene: `git status --porcelain -- data/ logs/` → empty (PASS)
- Encoding: README.md first bytes `23 20 e4` (`# ` + UTF-8) — no BOM (PASS)

## Byte-Truth Notes (grep of routers during Task 1/2)

- Route decorators verified: `api/main.py` — `@app.get("/health")` (L46), `openapi_url="/openapi.json"` (L36); `api/state.py` — `@router.get("/v1/state/{name}")` (L83), `@router.get("/health/ready")` (L103); `api/private.py` — router-level `Depends(require_api_key)` (L55), `@router.get("/v1/private/{name}")` (L157); `api/actions.py` — router-level auth (L44), `@router.post("/v1/actions/{kind}")` (L71), `@router.get("/v1/jobs/{job_id}")` (L118). No corrections needed — table and README match the code 1:1.
- 409 semantics verified at the raise sites (api/actions.py L104-115 + api/errors.py L55-69): detail carries `message` key both shapes; memory-claim hit → code `already_running` + `running_job_id`; OS-lock-only hold → `already_running_other_entry`, no job_id. README wording scoped to these facts.
- No `/v1/private` or `/v1/actions` row is public; no 公开级 row is key-protected; 机密级 rows name exactly the three families (plan prohibitions 1-2 hold).

## Decisions Made

- **README.md stays out of git (CLAUDE.md precedence, deviation 1):** plan step 7 (commit README) contradicts the 2026-08-31 user rule recorded in repo CLAUDE.md (项目说明 一律不上传 GitHub, 已 gitignore) and .gitignore L30. Executor rule: CLAUDE.md > plan instructions. Content delivered to the local file (SC5 documented-limits satisfied on the document the 04-07 gate reads); the commit step is waived and documented — force-adding a gitignored privacy-scoped file would reverse a signed user decision and could ride a future push to the possibly-public remote (PROJECT.md Context 安全注意).
- **README insertion point:** the [ASSUMED] API section did not exist (file is a stale v2-era 71-line strategy doc) — section created additively before 许可证 per 04-PATTERNS ("additive at the end").
- No user decision was required — no checkpoints in this plan; both tasks `type="auto"`.

## Deviations from Plan

### Auto-fixed / Rule-Driven Adjustments

**1. [CLAUDE.md precedence — commit scope] Task 2's README.md commit waived; content delivered local-only**
- **Found during:** Task 2 (commit step 7)
- **Issue:** The plan directs `docs(04-06): README known-limits + SC5 evidence` with specific-path staging of README.md — but README.md is untracked AND gitignored (.gitignore L30) by the user's standing 2026-08-31 decision (repo CLAUDE.md: 项目说明 README/CLAUDE/CONTEXT 等一律不上传 GitHub, 仅本地; commit f65c5bf removed it from the repo). Committing it would require `git add -f` on a privacy-scoped ignored file — reversing a signed user decision and risking a leak to the possibly-public remote via a future push.
- **Fix:** Applied the CLAUDE.md rule (takes precedence over plan instructions): wrote the full known-limits section to the local README.md (SC5 content deliverable met — the 04-07 gate reviews the local file), ran and recorded all three SC5 scans, and waived the commit. Scan evidence + section content are captured in this SUMMARY (committed in the plan metadata commit).
- **Files modified:** README.md (working tree only — remains untracked/ignored)
- **Verification:** all three SC5 scans pass (evidence above); no staged/committed change touches README.md (`git show --name-only b8e9169` = PROJECT.md only); suite green; hygiene clean
- **Committed in:** n/a — intentional absence, documented here and in the completion report

---

**Total deviations:** 1 documented (CLAUDE.md-driven commit waiver — not an auto-fix of a bug; a scope adjustment required by the project's privacy rule)
**Impact on plan:** The SC5 documentation clause is satisfied on the local document exactly as the 04-07 gate consumes it. The plan's must-have truths 1-4 hold on disk; truth 5 (docs-only diff) holds — but only one of the two docs files exists in git history, which the 04-07 reviewer should be aware of when reading the local README.

## Issues Encountered

- **None.** The byte-truth greps produced zero corrections (table ↔ routers 1:1); the three SC5 scans passed on first execution; no encoding issues (README UTF-8 no BOM; console output ASCII).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **04-07 live gate** now needs only machine-truth checks: README known-limits content vs the running service (409/422 shapes, endpoint inventory), boot posture against the real launcher (run_api.bat loopback default), and recording the Mac-side crontab state from the actual machine (asserted from 04-CONTEXT here, per the plan's flagged assumption).
- PROJECT.md classification table is the standing reference for phase-05 planners and reviewers — endpoint decisions start from the table, and any future reclassification is a reviewable 定稿-marked diff.
- Full suite: 148 passed, 1 skipped; `git status --porcelain -- data/ logs/` empty throughout.

---
*Phase: 04-exposure-hardening-data-classification*
*Completed: 2026-09-04*

## Self-Check: PASSED

Files verified present: .planning/PROJECT.md (classification table grep-verified), README.md (known-limits section grep-verified), 04-06-SUMMARY.md. Commit verified in git log: b8e9169 (docs; name-only output exactly `.planning/PROJECT.md`). Task 1 verify gates all passed (pytest 148 passed / 1 skipped, git show --stat lists PROJECT.md, family grep = 6, data/ logs/ hygiene empty). Task 2 SC5 scans all passed (git history empty for data/api_token.txt, sync_cloud grep clean, .gitignore covers token + logs, hygiene empty). README.md intentionally uncommitted (deviation 1 — user 2026-08-31 rule, CLAUDE.md precedence).
