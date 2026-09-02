---
phase: "2"
slug: "read-only-state-endpoints-defensive-read-layer"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-03"
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + fastapi TestClient (httpx 0.25.2) |
| **Config file** | pytest.ini (`pythonpath = .`, `testpaths = tests`) |
| **Quick run command** | `python -m pytest tests/test_state.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_state.py -q`
- **After every plan wave:** Run `python -m pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~5 seconds

---

## Per-Task Verification Map

Task IDs and waves are assigned by the planner (§8); rows are requirement-level and map 1:1 onto the tasks that touch each behavior. Threat Ref is filled once the plan's `<threat_model>` is authored.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (planner) | 02 | (planner) | STA-01 | — | Verbatim body bytes (CRLF fixture) + exact X-Data-Mtime/X-Data-Age-S headers + content-type application/json | unit (TestClient) | `python -m pytest tests/test_state.py -q` | ❌ W0 | ⬜ pending |
| (planner) | 02 | (planner) | STA-01 | — | Whitelist: 3 names 200; unknown name 404 `{"detail": ...}`; no path traversal surface | unit | same | ❌ W0 | ⬜ pending |
| (planner) | 02 | (planner) | STA-03 | — | Read layer: open/read/close per attempt; decode-error retry (injected reader, timer-free) succeeds; cache updated | unit | same | ❌ W0 | ⬜ pending |
| (planner) | 02 | (planner) | STA-03 | — | Persistent decode failure + warm cache → 200 + `X-Data-Stale: true` + last-good body + cached mtime; no stale header on fresh | unit | same | ❌ W0 | ⬜ pending |
| (planner) | 02 | (planner) | STA-03 | — | Persistent decode failure + empty cache → 503 `{"detail": ...}` (never bare 500) | unit | same | ❌ W0 | ⬜ pending |
| (planner) | 02 | (planner) | STA-03 | — | Missing/unreadable file → 503 (OSError skips retries) | unit | same | ❌ W0 | ⬜ pending |
| (planner) | 02 | (planner) | STA-03 | — | 0×5xx hammer during truncate-rewrite loop (warm cache) — every body valid JSON | integration | same | ❌ W0 | ⬜ pending |
| (planner) | 02 | (planner) | HLT-02 | — | /health/ready: all 3 present → 200; missing / directory → 503; ancient mtime → still 200 | unit | same | ❌ W0 | ⬜ pending |
| (planner) | 02 | (planner) | SC4 | — | Grep audit: no network tokens in api/*.py (source-scan regression test + standalone grep command in plan) | static | `grep -nE "(requests\|urllib\|httpx\|aiohttp\|socket)" api/*.py` + pytest source-scan | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_state.py` — covers STA-01, STA-03, HLT-02, SC4 (all new; no state tests exist today)
- [x] Framework already installed — pytest 9.1.1 / httpx 0.25.2 / TestClient verified this session; no install step
- [x] Existing `tests/conftest.py` autouse fixtures (net-block, env isolation, temproot) apply without change — no new fixtures required

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live 0×5xx observation during a real pipeline run | SC2 (ROADMAP) | Real writer concurrency cannot be reproduced deterministically in a unit hammer test | Run `python scripts/daily/run_pipeline.py` while polling GETs of all 3 names; observe 0 × 5xx and every body valid JSON |
| curl smoke against resident service | SC1 / SC3 | Resident-service restart path (run_api.bat) lives outside pytest | Restart service via run_api.bat; `curl -i http://127.0.0.1:8000/v1/state/market_state` and `/health/ready`; verify headers + verbatim body |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < ~5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
