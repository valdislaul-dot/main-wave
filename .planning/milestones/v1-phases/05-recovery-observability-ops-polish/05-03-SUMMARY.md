---
phase: 05-recovery-observability-ops-polish
plan: 03
subsystem: ops
tags: [docs, known-limits, scheduled-task, windows, readme, classification, mac-checklist]

# Dependency graph
requires:
  - phase: 05-01
    provides: as-built /health/details contract (path, tier, gate, 401/403, body shape) the README + PROJECT.md rows document
  - phase: 05-02
    provides: as-built bounded-footprint facts (5 MiB console.log .1 rotation, 20-pair registry cap) the README bounded-log paragraph states
provides:
  - README.md (local-only, gitignored) known-limits extension: D-37 deployment-lifecycle note (Ctrl+C vs AtStartup), /health/details endpoint row + auth/body contract, bounded-log paragraph, D-35 Mac verification checklist
  - .planning/PROJECT.md 定稿 classification-table row: GET /health/details 机密级 (api/health.py, router-level require_api_key) — additive-only
  - .planning/STATE.md [P3→P5] tracker row CLOSED with the D-36 live audit evidence (confirmed absent, 2026-09-05)
affects: [05-04 (real-machine live gate + SC3 final suite — the Mac checklist's exact Win counts land in its SUMMARY; Mac back-fill recorded there)]

actuals:
  tokens: 671    # chars/4 over realized diff (2,684 chars: 655 committed tracked + 2,029 local README additions)
  tasks: 3
  commits: 2

tech-stack:
  added: [none — docs/records only, zero package installs]
  patterns: ["Additive-only 定稿-table discipline: new 机密级 row as a standalone physical row (0 deletion lines in git diff), existing 定稿 row text byte-untouched", "Verify-only audit discipline (D-02): scheduler READS only; disable actions are user-only"]

key-files:
  created: []
  modified: [README.md (local-only), .planning/PROJECT.md, .planning/STATE.md]

key-decisions:
  - "PROJECT.md 定稿 table row realized as a standalone new 机密级 row (tier/endpoint/gate/source columns) rather than an in-cell append: the existing 定稿 row line stays byte-identical and the git diff is literally additive-only (3 insertions, 0 deletions) as the task verify demands — column semantics preserved"
  - "D-36 live audit outcome = CONFIRMED ABSENT: name-filtered enumeration output empty (exit 0), control enumeration healthy (201 tasks, only gogo-api relevant and registered Ready) → no disable command needed, no handoff; row closed 2026-09-05"
  - "Mac checklist suite wording uses the plan-fixed floor '157+ passed, 1 env-conditional skip' and points to the 05-04-SUMMARY.md exact Win counts for parity (current Win-side measured 185 passed 1 skipped after 05-02; floor wording kept per the plan's flagged assumption)"
  - "README stays local-only under the 2026-08-31 upload-scope rule: git check-ignore exits 0 and the plan commit excluded it — the Mac checklist reaches Mac via the user's git pull of the tracked code (Phase 3 cross-machine pattern)"

requirements-completed: [OPS-03]

coverage:
  - id: D1
    description: "README.md known-limits extension (local-only, gitignored): D-37 deployment-lifecycle note (interactive Ctrl+C stops the instance, AtStartup survives reboot and relaunches — no-code-change wording), /health/details endpoint row + auth contract (机密级, X-API-Key; no key 401 missing API key + WWW-Authenticate: ApiKey challenge; wrong key 403 invalid API key; 200 body {versions, uptime_seconds, last_check}; /health and /health/ready stay public), bounded-log paragraph (5 MiB boot rotation to console.log.1 one generation, 20 terminal-pair registry cap, no hand-cleaning), and the numbered D-35 Mac verification checklist (git pull → pytest -q full suite → conftest network-blocking proof → endpoint smoke with the data/api_token.txt token)"
    verification:
      - kind: other
        ref: "git check-ignore README.md (exit 0)"
        status: pass
      - kind: other
        ref: "grep -c 'console.log.1' README.md (1) && grep -c 'Mac' README.md (5)"
        status: pass
      - kind: other
        ref: "grep headers: 部署生命周期注意(D-37)/鉴权与响应体/日志有界行为/Mac 端验证清单 all present"
        status: pass
    human_judgment: false
  - id: D2
    description: ".planning/PROJECT.md 定稿 data-classification table gains the GET /health/details 机密级 row: standalone row with tier (机密级), endpoint, gate (X-API-Key 必填, 版本/uptime/最近检查详情; router 级 Depends(require_api_key), same dependency object as /v1/private/*), route source api/health.py, plus a one-line D-29/D-31 contract annotation — existing 定稿 rows untouched"
    verification:
      - kind: other
        ref: "grep -n '/health/details' .planning/PROJECT.md (row at line 65 + annotation 67)"
        status: pass
      - kind: other
        ref: "git diff --numstat .planning/PROJECT.md (3 additions, 0 deletions)"
        status: pass
    human_judgment: false
  - id: D3
    description: "D-36 live audit executed and the [P3→P5] tracker row closed in .planning/STATE.md: Get-ScheduledTask name-filter enumeration (pipeline|流水线|主升浪) output EMPTY with exit 0; control enumeration 201 total tasks with only gogo-api relevant (registered, Ready); confirmed absent → no disable command; row records audit date 2026-09-05, command, empty result and the close-out line"
    verification:
      - kind: other
        ref: "powershell Get-ScheduledTask filter enumeration (exit 0, empty output) — run twice"
        status: pass
      - kind: other
        ref: "git diff .planning/STATE.md shows audit date + result + close-out in the [P3→P5] row"
        status: pass
    human_judgment: false

# Metrics
duration: 4min
completed: 2026-09-05
status: complete
---

# Phase 5 Plan 3: Ops documentation + legacy close-out — README known-limits/Mac checklist (D-37/D-35), PROJECT.md /health/details classification row, D-36 scheduled-task audit record Summary

**D-35/D-36/D-37 docs-and-records close-out shipped with zero code changes: README (local-only) gained the D-37 Ctrl+C-vs-AtStartup deployment-lifecycle note, the /health/details auth contract (机密级, 401 missing-key challenge / 403 wrong-key, {versions, uptime_seconds, last_check} body), the bounded-log paragraph (5 MiB → console.log.1 one generation, 20-pair registry cap) and the numbered Mac verification checklist; PROJECT.md's 定稿 classification table gained the /health/details 机密级 row (api/health.py, router-level require_api_key) as a purely additive diff; and the [P3→P5] 15:30-task tracker closed with a live Get-ScheduledTask audit — enumeration empty, control healthy, no disable command needed.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-09-04T16:59:36Z
- **Completed:** 2026-09-04T17:03:09Z
- **Tasks:** 3
- **Files modified:** 3 (README.md local-only + PROJECT.md + STATE.md; 0 code files)

## Accomplishments

- **README.md (local-only, gitignored — never committed)**: endpoint quick-reference table gained the `GET /health/details` row (X-API-Key, 机密级); four new subsections under the API known-limits area, all written from the 05-01/05-02 as-built facts (never invented): (1) `### 部署生命周期注意：交互会话 Ctrl+C 与 AtStartup 自启（D-37）` — interactive-console Ctrl+C stops the instance (2026-09-03 4x ^C observations, LastTaskResult 0xC000013A) while the AtStartup autostart survives reboot and relaunches; recorded as a known characteristic with explicit NO-code-change wording (no watchdog, no relaunch logic); consequence: check service state via the scheduled task / /health after interactive sessions; (2) `### /health/details：鉴权与响应体（机密级）` — router-level `Depends(require_api_key)` same dependency object as `/v1/private/*`; no key → 401 missing API key + `WWW-Authenticate: ApiKey` challenge, wrong key → 403 invalid API key (no challenge); 200 body `{versions, uptime_seconds, last_check}`; /health + /health/ready stay public; (3) `### 日志有界行为` — 5 MiB boot rotation into `console.log.1` (one generation), 20 terminal-pair (.json+.log) registry cap, no hand-cleaning needed; (4) `### Mac 端验证清单（D-35, 跨机 rollout）` — numbered steps: git pull → `python -m pytest -q` (floor: 157+ passed, 1 env-conditional skip; exact Win counts land in the 05-04 SUMMARY, Mac counts back-filled by the user) → conftest `_no_network` autouse fixture proof (any network-touching test AssertionErrors — that IS the SC3 proof) → endpoint smoke (GET /health public; GET /health/details with X-API-Key token from data/api_token.txt).
- **.planning/PROJECT.md**: the 定稿 classification table now covers `GET /health/details` as a standalone 机密级 row — gate X-API-Key 必填 (router 级 `Depends(require_api_key)`, same dependency object as `/v1/private/*`), route source api/health.py — with a one-line annotation citing the contract source (05-CONTEXT D-29/D-31, as-built 05-01-SUMMARY). Diff is purely additive (3 insertions, 0 deletions); the Phase 4 定稿 row text is byte-untouched.
- **.planning/STATE.md [P3→P5] tracker row CLOSED (2026-09-05)**: D-36 live audit ran cleanly (exit 0) with EMPTY output — verbatim record of the enumeration command and result in the row; control enumeration healthy (201 total tasks; only gogo-api relevant and registered, State Ready). The 15:30 task is confirmed absent → **no disable command is needed**; Phase 3's D-02 disable/removal conclusion re-confirmed by live evidence instead of assumption.
- Zero code changes, zero package installs (threat model T-05-SC not triggered); no drift branch was taken.

## Task Commits

Each task was committed atomically:

1. **Task 1: README known-limits deployment note + Mac checklist** - no commit by rule (README.md is gitignored local-only under the 2026-08-31 upload-scope rule — verified `git check-ignore README.md` exit 0; content verified by grep, excluded from all commits)
2. **Task 2: PROJECT.md classification row** - committed with Task 3 in the scoped plan commit below (plan-directed: tasks 2+3 share one scoped commit when the audit lands the same day)
3. **Task 3: D-36 live audit + STATE.md close-out** - `ea58d8c` (docs(05): classification row + D-36 audit record (OPS-03 docs)) — .planning/PROJECT.md + .planning/STATE.md only

**Plan metadata:** `docs(05-03): complete ops documentation + legacy close-out plan` (this SUMMARY + STATE/ROADMAP/REQUIREMENTS updates) — see git log.

## Files Created/Modified

- `README.md` (MOD, local-only/gitignored) — endpoint table row + 4 subsections: D-37 deployment-lifecycle note, /health/details auth contract, bounded-log paragraph, D-35 Mac checklist (as-built facts from 05-01/05-02 SUMMARYs)
- `.planning/PROJECT.md` (MOD, tracked) — 定稿 classification table: standalone 机密级 row for GET /health/details (source api/health.py, router-level require_api_key gate) + D-29/D-31 annotation; additive-only
- `.planning/STATE.md` (MOD, tracked) — [P3→P5] blocker row closed with D-36 audit date 2026-09-05 + verbatim enumeration evidence; Current Position advanced to Plan 4 of 4

## Decisions Made

- **Row shape for the 定稿 table**: a standalone new 机密级 row (not an in-cell append to the existing 机密级 line). The existing row's line would have registered as a deletion in the git diff under in-cell appending, violating the task's additive-only verify; the standalone row keeps the 定稿 text byte-identical and the diff at 0 deletions while preserving the exact column semantics (tier / endpoint / gate / route source).
- **D-36 outcome recorded as confirmed-absent with control evidence**: the scoped enumeration returned empty; to make the empty result meaningful as evidence (not a silent enumeration failure), the audit also recorded the control run — 201 total tasks enumerated, only gogo-api relevant and registered Ready. No disable command was needed and none was issued (D-02 discipline; the drift branch was never entered).
- **Suite-count wording in the checklist**: the plan-fixed floor "157+ passed, 1 env-conditional skip" is stated, with exact Win counts deferred to the 05-04 SUMMARY and Mac counts to the user's back-fill — the checklist is written before the final Win count exists (plan's flagged assumption honored; current measured baseline after 05-02 is 185 passed 1 skipped).

## Deviations from Plan

None - plan executed exactly as written.

- **Total deviations:** 0
- **Impact on plan:** N/A

## Issues Encountered

None. (Note: the audit corroboration run — counting all tasks and confirming gogo-api — was added inside the task's own evidence discipline, not as a deviation; the enumeration itself ran twice with identical empty output.)

## User Setup Required

None - no external service configuration required. The Mac-side verification run itself is the user's cross-machine rollout step (D-35 checklist in README); results are back-filled by the user per the Phase 3 pattern.

## Next Phase Readiness

- README now documents the as-built lifecycle/endpoint/log-bound facts (D-37, 05-01/05-02 contract) for the operator on this machine, and the Mac checklist (D-35) is ready for the user's cross-machine rollout run.
- The 15:30 scheduled-task question is closed with live evidence (D-36); no lingering disable action exists.
- 05-04 (real-machine live gate: SC1 live matrix + rotation proof + SC3 final suite + human review) can cite this plan's records; the exact Win suite counts recorded in the 05-04 SUMMARY become the Mac parity baseline the checklist points to.
- End-of-phase human review note: the Mac checklist is written to a local-only file by design (upload-scope rule) — the Mac user reaches the code via git pull and executes the steps listed in the README segment inventory above; no drift-branch handoff occurred this plan.

## Self-Check: PASSED

- FOUND: README.md (git check-ignore exit 0; console.log.1 ×1, Mac ×5, all four section headers present)
- FOUND: .planning/PROJECT.md /health/details row (line 65) + annotation (line 67); diff 3 insertions 0 deletions
- FOUND: .planning/STATE.md [P3→P5] row closed with 2026-09-05 audit date + enumeration evidence
- FOUND (git log): ea58d8c — scoped docs(05) commit holding PROJECT.md + STATE.md only

---
*Phase: 05-recovery-observability-ops-polish*
*Completed: 2026-09-05*
