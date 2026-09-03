---
phase: 04-exposure-hardening-data-classification
plan: 05
subsystem: api
tags: [sec-03, wr-01, d-12, boot-check, env-forced-token, fastapi, capsys, regression]

# Dependency graph
requires:
  - phase: 04-exposure-hardening-data-classification (04-01)
    provides: "api/main.py boot-region baseline after the envelope wiring (handler region above the boot sequence) — the SEC-03 branch this plan rewrites sat below those lines, byte-frozen"
  - phase: 04-exposure-hardening-data-classification (04-03)
    provides: "api/main.py include_router lines landed above the boot sequence — this plan's branch edit is wave-serialized below them; /v1/private exposure precondition (the boot gate this plan hardens)"
provides:
  - "WR-01/D-12 boot fix: non-loopback binds accept ONLY a non-empty stripped GOGO_API_TOKEN env var — data/api_token.txt (auto-generated or not) no longer satisfies the gate (WR-01 root cause: has_token shared by both postures, now structurally removed — the non-loopback branch reads os.environ directly)"
  - "ASCII refusal to stderr + sys.exit(1) before any token/file creation (SEC-03 ordering preserved: env parse -> fail-closed check -> loopback ensure_token only); ASCII non-loopback warning to stderr whenever env-authorized exposure proceeds, never echoing the token value (T-04-18)"
  - "WR-01 regression test coverage (SC2): file-token-only refusal case + env-token warning pins in tests/test_boot.py (17 tests green)"
affects: [04-07 (real-machine live gate re-verifies the boot path against the actual launcher posture — run_api.bat binds loopback default per D-08 so no launcher change is needed for the default posture), verify-work, phase-05 ops polish]

actuals:
  tokens: 1650   # chars/4 over the realized diff (6596 chars across api/main.py + tests/test_boot.py, git show --format= measure)
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Env-only satisfier at the boot boundary: the exposure-authorized branch reads os.environ.get directly instead of a shared file-token helper — file presence is structurally irrelevant to the non-loopback posture (WR-01 root-cause removal by construction, not by message wording)"
    - "Boot refusal ordering pin: refusal precedes ensure_token AND uvicorn.run (recorder-fake assertion), keeping SEC-03's fail-closed check the first side-effect-free gate"

key-files:
  created: []
  modified:
    - api/main.py - SEC-03 non-loopback branch rewritten (env-only satisfier + ASCII warning); main() docstring second paragraph refreshed for D-12 semantics; loopback branch, branch order, /health, 04-01/04-03 wiring byte-untouched
    - tests/test_boot.py - module docstring + case 8 (file-token-only refusal) + case 9 (env-token warning pin); case 7 comment-only clarification; case 5 byte-untouched

key-decisions:
  - "Refusal message retains the two case-5 pinned substrings ('0.0.0.0' via {host} interpolation and 'GOGO_API_TOKEN') while dropping the old remedy text that named data/api_token.txt — new message states env-var-only + file-token-not-accepted with no paths beyond the host (plan prohibition), which is why case 5 needed ZERO assertion deltas"
  - "Warning printed to stderr (not stdout): case 7's stdout-only pin ('captured.out == \"\"') survives byte-unchanged — only a comment was appended to explain why the D-12 warning does not disturb it"
  - "main() docstring second paragraph refreshed ('env+file 现存状态' -> '只认 env 现存状态, WR-01/D-12: 文件 token 不再满足') — the old text described the WR-01 buggy semantics and would misdocument the fix (Rule 1 stale-doc fix, same family as 04-01 deviation 2)"
  - "File-token refusal test seeds the token file with a sentinel and asserts bytes unchanged + uvicorn.run never called — pins that the refusal precedes ensure_token/uvicorn without racing on file creation"

patterns-established:
  - "Boot-gate regression triple-pin: SystemExit code + stderr substring (host + env var) + no-side-effect (file bytes unchanged, uvicorn recorder empty)"
  - "Token-echo audit via capsys both-streams assertion: warning case asserts the literal token value absent from captured.out AND captured.err"

requirements-completed: [STA-02, SEC-02]

coverage:
  - id: D1
    description: "Non-loopback bind refused unless a non-empty stripped GOGO_API_TOKEN env var is set; file-token-only (the WR-01 regression) exits 1 with the ASCII error naming host + GOGO_API_TOKEN before any token/file creation or uvicorn.run"
    requirement: SEC-02
    verification:
      - kind: unit
        ref: "tests/test_boot.py#test_non_loopback_file_token_only_refuses_without_uvicorn"
        status: pass
      - kind: unit
        ref: "tests/test_boot.py#test_non_loopback_without_token_refuses_and_creates_no_file (case 5, unchanged)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Env-authorized non-loopback bind proceeds and prints an ASCII warning to stderr naming host + GOGO_API_TOKEN with the token value absent from all captured output; loopback default (auto-generate file token) byte-unchanged"
    requirement: SEC-02
    verification:
      - kind: unit
        ref: "tests/test_boot.py#test_env_token_non_loopback_proceeds_with_ascii_warning_no_token_echo"
        status: pass
      - kind: unit
        ref: "tests/test_boot.py#test_env_token_satisfies_non_loopback_check (case 7, assertion-unchanged)"
        status: pass
      - kind: unit
        ref: "tests/test_boot.py#test_loopback_boot_prints_only_notice_and_creates_token (loopback parity)"
        status: pass
      - kind: unit
        ref: "python -m pytest -q (148 passed, 1 skipped — full-suite regression gate)"
        status: pass
    human_judgment: false

# Metrics
duration: 6min
completed: 2026-09-04
status: complete
---

# Phase 04 Plan 05: WR-01 Boot Fix (D-12) — Env-Forced Token for Non-Loopback Binds Summary

**The boot boundary now refuses non-loopback exposure unless GOGO_API_TOKEN is deliberately set in the environment — the auto-generated data/api_token.txt file can no longer authorize a 0.0.0.0 bind (WR-01 closed by construction: the non-loopback branch reads os.environ directly, has_token is structurally irrelevant there) — with a loud ASCII stderr warning on every env-authorized exposed bind that never echoes the token, and both behaviors pinned by new regression cases in tests/test_boot.py (case 8 file-token refusal, case 9 warning pin)**

## Performance

- **Duration:** 6 min
- **Started:** 2026-09-04 05:04 (+08:00)
- **Completed:** 2026-09-04 05:10 (+08:00)
- **Tasks:** 2
- **Files modified:** 2 (api/main.py + tests/test_boot.py)

## Accomplishments

- **WR-01 regression closed (Task 1):** the non-loopback SEC-03 branch now accepts only `os.environ.get("GOGO_API_TOKEN", "").strip()` non-empty. The file token (auto-generated or not) no longer satisfies the gate — the shared-`has_token` root cause is removed structurally because the branch never consults the file. Refusal prints an ASCII error naming the bound host and `GOGO_API_TOKEN` to stderr and exits 1 BEFORE any token generation or file creation (SEC-03 ordering preserved: env parse → fail-closed check → `ensure_token` only on the loopback branch).
- **Loud exposure (D-12):** whenever an env token authorizes a non-loopback bind, an ASCII warning is printed to stderr before the normal boot order (`reload_registry` → `uvicorn.run` both byte-untouched). The warning is a fixed string with no token interpolation — the token value can never reach the console.
- **Loopback default byte-unchanged:** `has_token`/`ensure_token` file fallback for 127.0.0.1 (auto-generate `data/api_token.txt`) is the Phase 1 payload, untouched; boot sequence and 04-01/04-03 wiring stay diff-auditable (this plan's diff touches only the SEC-03 branch region + the main() docstring paragraph describing it).
- **Test coverage (SC2, Task 2):** case 8 pins the actual WR-01 regression — file token present, env absent → SystemExit(1), refusal names host + env var, uvicorn.run never called, the pre-existing token file never rewritten; case 9 pins the warning — env token set → boot proceeds (patched uvicorn), stderr warning names host + env var, literal token value absent from both captured streams. Case 5 (no-token refusal) and case 7 (env-satisfies) needed ZERO assertion deltas.
- **Full suite:** boot suite 17 passed; full suite 148 passed, 1 skipped (baseline 146 + 2 new); `git status --porcelain -- data/ logs/` empty after every stage.

## Pre-Edit SEC-03 Branch (api/main.py, as of HEAD~1)

```python
    if not is_loopback(host):
        # SEC-03: 非回环绑定必须有已配置 token, 否则拒绝启动 (exit non-zero)。
        # 只评估 env/file 状态 —— 本分支绝不调用 ensure_token。
        if not has_token(token_path):
            print(
                f"ERROR: refusing to bind {host} without an API token. "
                "Set GOGO_API_TOKEN or create data/api_token.txt",
                file=sys.stderr,
            )
            sys.exit(1)
```

## Post-Edit SEC-03 Branch (as committed)

```python
    if not is_loopback(host):
        # SEC-03 (WR-01/D-12): 非回环绑定只接受环境变量 GOGO_API_TOKEN (strip 后非空)。
        # 文件 token (data/api_token.txt, 含自动生成) 不再满足检查 —— 自动生成的文件与
        # 误配无从区分 (WR-01 根因: has_token 曾被两种姿态共享)。本分支只评估 env 状态,
        # 绝不调用 ensure_token / 绝不创建任何文件 (fail-closed 检查先于一切 token 生成)。
        if not os.environ.get("GOGO_API_TOKEN", "").strip():
            print(
                f"ERROR: refusing to bind {host}: GOGO_API_TOKEN is required for "
                "non-loopback binds. A file token is not accepted - set the "
                "GOGO_API_TOKEN environment variable to authorize exposure",
                file=sys.stderr,
            )
            sys.exit(1)
        # D-12: 绑定暴露总是大声 —— 每次非回环启动都打印 ASCII 警告, 绝不回显 token 值。
        print(
            f"WARNING: binding {host} with API token from GOGO_API_TOKEN "
            "(non-loopback exposure)",
            file=sys.stderr,
        )
```

Also changed: main() docstring second paragraph — "非回环分支的 token 检查基于 env+文件现存状态" → "非回环分支的 token 检查只认 env 现存状态 (WR-01/D-12: 文件 token 不再满足非回环检查)" (the old text described the WR-01 buggy semantics).

## Exact Console Text (host = 0.0.0.0)

- Refusal (stderr, then `sys.exit(1)`):
  `ERROR: refusing to bind 0.0.0.0: GOGO_API_TOKEN is required for non-loopback binds. A file token is not accepted - set the GOGO_API_TOKEN environment variable to authorize exposure`
- Warning (stderr, env token present):
  `WARNING: binding 0.0.0.0 with API token from GOGO_API_TOKEN (non-loopback exposure)`

Both ASCII-only, no paths beyond the host, no token echo. No new console output on the loopback path.

## New Test Cases (tests/test_boot.py)

| Case | Name | Pins |
|------|------|------|
| 8 | `test_non_loopback_file_token_only_refuses_without_uvicorn` | File token `file-key\n` seeded, env absent → `SystemExit` code 1; stderr contains `0.0.0.0` + `GOGO_API_TOKEN`; recorder-fake `uvicorn_calls == []` (refusal precedes uvicorn.run); file bytes unchanged (refusal precedes ensure_token) |
| 9 | `test_env_token_non_loopback_proceeds_with_ascii_warning_no_token_echo` | Env `boot-test-token-abc`, file absent → no SystemExit, no file created; stdout empty; stderr contains `0.0.0.0` + `GOGO_API_TOKEN`; token value absent from both streams |

## Case 5/7 Deltas Applied

- **Case 5** (`test_non_loopback_without_token_refuses_and_creates_no_file`): zero deltas — the new refusal message retained both pinned substrings (`0.0.0.0` via `{host}`, `GOGO_API_TOKEN`) and the no-file-created behavior.
- **Case 7** (`test_env_token_satisfies_non_loopback_check`): zero assertion deltas — it pins stdout only (`captured.out == ""`), and the D-12 warning goes to stderr; a trailing comment was added explaining why the warning does not disturb the pin.
- Module docstring: added the case-8 WR-01 load-bearing line.

## Task Commits

Each task was committed atomically:

1. **Task 1: api/main.py D-12 SEC-03 branch rewrite** — `a57476b` (fix; 17+/7-; boot suite full green before the test commit — the pre-existing 15 cases survived the new branch with zero expected-byte deltas)
2. **Task 2: WR-01 regression cases + warning pins** — `8d505b7` (test; 49+/2-; boot suite 17 passed, full suite 148 passed 1 skipped)

**Plan metadata:** pending final docs commit.

## Files Created/Modified

- `api/main.py` - modified; SEC-03 non-loopback branch env-only satisfier + ASCII warning; main() docstring paragraph refresh; nothing else changed (loopback branch, `has_token`/`ensure_token` imports and loopback use, `reload_registry`, `uvicorn.run`, /health, exception-handler wiring, include_router lines byte-untouched)
- `tests/test_boot.py` - modified; docstring line + case 8 + case 9 + case-7 comment; `_patch_uvicorn_run` (L22-25) reused verbatim by case 9; case 8 uses an inline recorder fake of the same shape

## Decisions Made

See key-decisions frontmatter. No user decision was required — no checkpoints in this plan; both tasks were `type="auto"` and all must-have truths verified by the suite:
- env-only satisfier, file never satisfies (Truth 1) — case 8 SystemExit + no-rewrite pin
- env-authorized bind proceeds + ASCII warning with no token echo (Truth 2) — case 9 capsys both-stream pin
- loopback default posture unchanged (Truth 3) — case 6/loopback tests green byte-unchanged
- fail-closed check has test coverage (Truth 4/SC2) — cases 8/9
- boot-region changes confined to the SEC-03 branch (+ its documenting docstring paragraph) (Truth 5) — diff shows api/main.py 17+/7- only in that region
- suite green + data//logs/ untouched (Truth 6) — 148 passed 1 skipped; hygiene empty after every stage

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Stale documentation] main() docstring still described the WR-01 file+env semantics**
- **Found during:** Task 1 (branch rewrite)
- **Issue:** The main() docstring second paragraph ("非回环分支的 token 检查基于 env+文件现存状态") documented the pre-fix behavior — the exact WR-01 bug this plan removes. Leaving it would misdocument the new env-only contract for future maintainers (same family as 04-01 deviation 2: stale comment contradicting the change)
- **Fix:** Refreshed the paragraph to state env-only semantics with the WR-01/D-12 reference; first docstring line (boot order) untouched
- **Files modified:** api/main.py (docstring only)
- **Verification:** Boot suite 15/15 green after the edit; hygiene clean
- **Committed in:** a57476b (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1)
**Impact on plan:** Minimal — documentation accuracy only, no behavior change beyond the plan's contract; no scope creep (diff confined to the SEC-03 branch region plus its describing docstring).

## Issues Encountered

- **None.** The plan's two anticipated test deltas did not materialize: case 5 survived because the new refusal message deliberately retained both pinned substrings, and case 7 survived because its pin is stdout-scoped while the D-12 warning targets stderr — both confirmed green before the Task 1 commit (15/15), which the plan explicitly allows ("a pass is also acceptable if the pre-existing assertions survive").

## User Setup Required

None - no external service configuration required. The live launcher (run_api.bat + Task Scheduler) binds the loopback default per D-08, so the default posture needs no GOGO_API_TOKEN task-env addition; if a future deployment binds non-loopback, GOGO_API_TOKEN must be supplied in that launcher's environment (flagged assumption, re-checked at the 04-07 live gate).

## Next Phase Readiness

- **04-07 live gate** can now re-verify the real boot path against the hardened branch: loopback default boots and auto-generates the token file exactly as before; any launcher that actually binds non-loopback without a task-env GOGO_API_TOKEN will halt loudly at boot (the gate records rather than weakens, per plan assumptions)
- WR-01 (P2 review item) is closed at the boot boundary; SEC-02's fail-closed boot check now has test coverage (SC2), not just documentation
- Full suite: 148 passed, 1 skipped; `git status --porcelain -- data/ logs/` empty throughout

---
*Phase: 04-exposure-hardening-data-classification*
*Completed: 2026-09-04*

## Self-Check: PASSED

Files verified present: api/main.py, tests/test_boot.py, 04-05-SUMMARY.md. Commits verified in git log: a57476b (fix), 8d505b7 (test). Boot suite 17 passed; full suite 148 passed, 1 skipped; data/ and logs/ untouched (hygiene empty after every stage).
