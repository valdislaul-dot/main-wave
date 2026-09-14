# Phase 03 — UI Review

**Audited:** 2026-09-04
**Baseline:** Abstract 6-pillar standards (no UI-SPEC.md exists for this phase)
**Screenshots:** not captured (no dev server — ports 3000/5173/8080/8501/8765 dead; port 8000 serves the resident API, which has no UI HTML; the Streamlit dashboard was not running). Code-only audit with full diff evidence.
**Audit scope:** Phase 03's only user-facing UI change is in `scripts/daily/gui_dashboard.py` (D-01 lock join, commit `d0df7a3`): the 🔄 刷新数据 branch acquires `data/locks/pipeline.lock`, shows `st.warning` when the lock is held (skip path), and warns on `subprocess.TimeoutExpired`. Git diff proves exactly two hunks (+20/−6 lines of which −6 are pure re-indentation); everything else in the file byte-identical. API error strings (401/403/404/409/503 `detail` bodies) are machine-readable JSON and were audited as API copywriting only.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | New timeout warning introduces "管线" — a term used nowhere else in the codebase — 11 lines below the sibling warning that uses the canonical "流水线" |
| 2. Visuals | 4/4 | No new visual surface; both warnings render through the established full-width `st.warning` primitive and persist on-frame without rerun |
| 3. Color | 4/4 | Zero color surface added (diff audit: no CSS/token/hardcoded values); yellow warning semantics correct for both new states |
| 4. Typography | 4/4 | No font size/weight/markdown added; plain-text strings match the existing `st.warning("无符合条件候选")` convention (line 268) |
| 5. Spacing | 4/4 | No spacing values or CSS added; framework-default warning box spacing identical to pre-existing usage |
| 6. Experience Design | 3/4 | Timeout path releases the lock while the child may still run; nothing but the warning text brakes an immediate re-click that would re-spawn concurrently (documented deferral to ACT-04 v2) |

**Overall: 22/24**

---

## Top 3 Priority Fixes

1. **Unify pipeline terminology in the new timeout warning** — `scripts/daily/gui_dashboard.py:102` says "管线可能仍在后台运行"; "管线" has exactly 1 occurrence in the entire `scripts/` tree (this line), while "流水线" is the canonical term across 18+ occurrences / 10 files including the sibling warning 11 lines above (`gui_dashboard.py:91` "流水线正在运行中…") and CLAUDE.md/run_pipeline.py docs. Same feature, two names, same branch. Fix: change "管线" to "流水线" → "刷新超时——流水线可能仍在后台运行,请查看日志后再试". Zero behavior risk, one string edit, and it makes the GUI surface terminology internally consistent.
2. **Add next-step guidance to the held-lock warning** — `gui_dashboard.py:91` states state/cause/consequence ("流水线正在运行中(API或其他入口),本次刷新已跳过") but no action, while the timeout warning right below it does give guidance ("请查看日志后再试"). The user's question after a skipped click is "when can I retry?" Fix: append a pointer, e.g. "…本次刷新已跳过,请稍后再点刷新" — mirrors the advisory shape of line 102 and closes the guidance asymmetry between the two new messages.
3. **Close the orphan-window re-entry affordance (or document it as accepted)** — after `TimeoutExpired`, `finally: fd.close()` releases the lock while the child may still be running (probe V4, documented). The UI immediately allows a re-click that re-acquires the free lock and spawns a second pipeline concurrently with the orphan — the exact double-run the single-flight lock exists to prevent; the warning copy is the only brake. This is a deliberate warn-and-release contract with cleanup deferred to ACT-04 v2 (03-03 SUMMARY Decisions 1-2), so it is not a phase defect — but until ACT-04 lands, consider a `st.session_state` re-click guard/cooldown after a timeout (e.g. refuse re-entry for the 180 s window), or record the warn-only state as an accepted risk in the GUI's docs.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

Surface audited: two new `st.warning` strings (the phase's only user-facing copy) + API `detail` strings.

**WARNING — terminology drift, "管线" vs canonical "流水线"** (`gui_dashboard.py:102`): the timeout warning uses "管线", which a full-tree grep shows appears **nowhere else** in `scripts/` (1 hit total). The canonical term "流水线" appears 18+ times across 10 files (`run_pipeline.py` ×6, `morning_check.py` ×4, `gui_dashboard.py` ×2 including the sibling warning at line 91, CLAUDE.md everywhere). Two messages about the same pipeline, 11 lines apart in the same branch, use two different names for it. Fix: line 102 → "刷新超时——流水线可能仍在后台运行,请查看日志后再试". (The plan's mandated warning texts are implemented byte-exact per the 03-03 contract — the drift comes from the plan's own pinned string, so fix it at the next copy touch-point with user awareness; the text was verified delivered as planned.)

**WARNING — guidance asymmetry between the two new warnings**: line 91 (held-lock skip) is purely declarative with no next step; line 102 (timeout) carries advice. The skip case is the one users will hit routinely (GUI click during an API-triggered run), and the missing "wait and retry" pointer leaves the action implied. Also, line 102's advice "请查看日志后再试" references a log that is not clearly defined for this run type: the GUI spawns `run_pipeline.py --fast` with `capture_output=True`, so the child's stdout is captured in memory and discarded on `TimeoutExpired` — there is no `logs/api/jobs/*.log` artifact for GUI-triggered runs (that registry belongs to API triggers). A user following the advice has no obvious "日志" to open. Suggest naming an observable the user can actually check (e.g. "请确认涨停池数据未在更新后再试" or, in v2 with ACT-04, write the orphan's output tail to a known file).

**Passing notes**: Messages are otherwise precise — they distinguish the three outcomes (skipped-busy / timed-out-maybe-running / completed-or-partial via the pre-existing `完成!` / `部分失败(见日志)`), use the user's language (Chinese; the API contract is English machine JSON, correctly kept separate), avoid terminal punctuation consistently with the file's convention (compare line 268 `st.warning("无符合条件候选")`), and match the plan-pinned strings byte-for-byte.

**API copywriting** (`api/auth.py:42,48`; `api/actions.py:70,78-85,100,104,106`): 401 "missing API key" / 403 "invalid API key" / 404 "unknown action kind" / 404 "job not found" / 409 "<kind> already running" (+ dual shapes: with/without `running_job_id`) / 503 "job temporarily unavailable" — consistent terse lowercase `{"detail": ...}` style that continues the Phase 2 D-04 minimal-JSON contract; the 409 message differs from the 03-01 registry-core's plain-English variant appropriately by carrying the machine-usable `running_job_id`. 404/409/503 bodies carry no token, path, or holder info (SEC-01). No changes recommended; "another entry point" parenthetical is terse but documented contract.

### Pillar 2: Visuals (4/4)

No new layout, hierarchy, icon, or container surface was added. Diff audit (`git show d0df7a3 -- scripts/daily/gui_dashboard.py`): exactly two hunks, zero style/markup lines. Both new messages render through Streamlit's stock `st.warning` box — the same primitive and placement path as the pre-existing warning at line 268 and the pre-existing `st.success("完成!")`/spinner in this branch. Note on placement: the branch executes at script top level (the button lives in column `c3` but the `st.warning` calls are outside any `with cN:` container), so warnings render full-width below the header row — a visible, standard location, not a cramped column. The deliberate no-rerun on warning paths means the held-lock notice persists on the current frame instead of being wiped — correct choice for a status the user must see. No screenshots available (dashboard not running); code-level evidence only.

### Pillar 3: Color (4/4)

Zero color surface introduced: no CSS lines, no hex/rgb values, no token references in either hunk. Semantics are correct: both new states use yellow `st.warning` — appropriate for "busy, refresh skipped" (non-error) and for "timeout, outcome unknown" (the child may still complete successfully; `st.error` red would overstate a confirmed failure, and the file's existing taxonomy reserves success/failure signaling for `st.success`/returncode messaging — `st.error` is unused across the dashboard). The two new warnings differ in consequence severity (informational skip vs potentially-running orphan) but share styling; acceptable because the copy carries the differentiation — worth revisiting only if ACT-04 later adds a confirmed-kill failure state, which would merit `st.error`.

### Pillar 4: Typography (4/4)

No font sizes, weights, or markdown emphasis were added. Both messages are plain strings rendered in stock component typography — identical treatment to the pre-existing `st.warning("无符合条件候选")` at line 268. No size/weight proliferation relative to the file's established set (CSS block at lines 28-37 untouched). Chinese text length (~21 and ~24 chars) renders comfortably at the file's 14px/12px mobile scale.

### Pillar 5: Spacing (4/4)

No spacing values, arbitrary units, or CSS additions in the diff; warning boxes use framework-default padding identical to the existing `st.warning`/`st.success` usage in the same branch and file. Nothing violates the abstract spacing standard. The code-side indentation restructure (the old branch body re-indented into `try:`) has no UI-spacing effect.

### Pillar 6: Experience Design (3/4)

State coverage of the newly touched interaction is otherwise complete and each finding below is against the *residual* gaps, not the phase contract (which was met: the plan's gates — acquire-before-run, finally-release, timeout warning — all verify, and the AppTest proved the held-lock click shows the warning with no spawn):

- **WARNING — orphan-window re-entry** (`gui_dashboard.py:101-106`): on `TimeoutExpired`, the fd closes in `finally` (release guarantee is correct and verified) while the child may still be alive and writing `data/`. The button is immediately re-clickable; a fast second click acquires the now-free lock and spawns a concurrent `run_pipeline --fast` against the orphan's writes — the single-flight violation this phase exists to prevent. The mitigation is textual only ("请查看日志后再试"). Deferred by explicit phase decision to ACT-04 v2 (taskkill cleanup) — recommend a session-state cooldown/guard until then, or an explicit accepted-risk note.
- **Minor — unexpected exceptions surface as raw tracebacks** (`gui_dashboard.py:93-104`): non-`TimeoutExpired` exceptions (e.g. `OSError` on spawn) reach `finally` (lock released — good) but propagate to Streamlit's default red traceback with no friendly message. Pre-existing pattern for this branch (before D-01 an exception behaved identically) and the plan mandated only `TimeoutExpired` handling — noted, not a regression. A catch-all `except Exception: st.warning(...)` would be a small hardening if the branch is touched again.
- **Passing**: held-lock path (visible warning, no spinner, no spawn, no rerun, frame preserved), success path (spinner → `完成!`/`部分失败(见日志)` → rerun, byte-identical to pre-D-01), timeout path (visible warning + guaranteed release), and fd release on every exit path including unexpected exceptions. The empty/failure states of the wider dashboard are untouched by this phase.

---

## Registry Safety

No `components.json` — shadcn not initialized; third-party registry audit skipped (not applicable to this Python/Streamlit project).

## Files Audited

- `scripts/daily/gui_dashboard.py` — full file (377 lines); the phase's only user-facing UI surface (lines 87-106 changed, rest byte-identical per `git show d0df7a3`)
- `api/auth.py` — user-facing HTTP error strings (401/403 detail bodies)
- `api/actions.py` — user-facing HTTP error strings (404/409/503 detail bodies)
- `api/jobs.py` — verified zero console/UI text (grep: no prints)
- `scripts/daily/job_lock.py` — verified zero console/UI text (content-free lock helper)
- `api/main.py` — diff-audited (+8 lines: imports/router/boot call; prints at lines 52-71 are pre-existing Phase 1 boot messages)
- Evidence sources: `03-01/03-02/03-03/03-04-SUMMARY.md`, `03-03-PLAN.md`, `03-CONTEXT.md`, commit `d0df7a3` full diff
