---
phase: "1"
slug: "service-skeleton-health-liveness"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-09-02"
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 8.3 (installed 2026-09-02 during execution; suite runs green) via TestClient (starlette 0.46.2) |
| **Config file** | `pytest.ini` — repo root: `[pytest]` / `pythonpath = .` / `testpaths = tests` (import mechanics, Pitfall 1) |
| **Quick run command** | `python -m pytest -q` |
| **Full suite command** | `python -m pytest` |
| **Estimated runtime** | ~1 second (18 passed, 1 skipped in 0.29s) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/<affected file> -q`
- **After every plan wave:** Run `python -m pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-T1 | 01-01 | 1 | HLT-01, SEC-03 | T-1-01 | /health returns 200 with no auth header (never 401); refusal branch never calls ensure_token | unit | `python -m pytest tests/test_health.py -q` | ✅ | ✅ green |
| 01-01-T2 | 01-01 | 1 | HLT-01, OPS-02 | — | suite runs green with zero network access (autouse blocker) | unit+infra | `python -m pytest tests/test_health.py -q` | ✅ | ✅ green |
| 01-01-T3 | 01-01 | 1 | SEC-03, OPS-02 | T-1-02 | non-loopback + no token → refusal, exit != 0, NO token file created; loopback → token generated; notice = D-05 sentence, no token value | unit | `python -m pytest tests/test_boot.py -q` | ✅ | ✅ green |
| 01-02-T1 | 01-02 | 2 | OPS-01 | — | bat-launched boot from any cwd; logs/api/console.log capture | e2e | `python -m pytest -q` (suite green) + live bat boot probe | ✅ | ✅ green |
| 01-02-T2 | 01-02 | 2 | OPS-01 | — | task registered exactly once; idempotent re-run; no stale hardcoded paths | manual+CLI | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/daily/install_api_task.ps1` | ✅ | ✅ green |
| 01-02-T3 | 01-02 | 2 | OPS-01 | — | Start-ScheduledTask → live 200 probe; State Running; no failure code | manual | `Start-ScheduledTask -TaskName "gogo-api"` then `python -c "import urllib.request,json; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)))"` | n/a | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `pip install "pytest>=8.3"` — installed 2026-09-02 during 01-01 execution
- [x] `pytest.ini` — root config with `pythonpath = .`, `testpaths = tests`
- [x] `tests/conftest.py` — autouse network-block fixture (loopback carve-out for Windows ProactorEventLoop) + env-isolation fixture
- [x] `tests/test_health.py` — HLT-01 contract tests (4 tests)
- [x] `tests/test_boot.py` — SEC-03/D-03/D-05 pure-function tests (15 tests)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Task Scheduler auto-start survives a Windows reboot | OPS-01 | Cannot assert OS Task Scheduler / reboot from pytest | Register task via installer, `Start-ScheduledTask -TaskName "gogo-api"`, probe http://127.0.0.1:8000/health → 200; reboot test completed as UAT test 1 (pass, 2026-09-03) |

---

## Validation Audit 2026-09-03

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

*All phase requirements have automated verification (HLT-01 / SEC-03 / OPS-02) or a completed manual verification (OPS-01, UAT test 1 pass). No auditor spawn needed.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-09-03
