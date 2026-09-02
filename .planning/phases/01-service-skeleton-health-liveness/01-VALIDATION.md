---
phase: "1"
slug: "service-skeleton-health-liveness"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-02"
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 8.3 (PyPI latest 9.1.1) via TestClient (starlette 0.46.2) — pytest NOT installed today [VERIFIED] |
| **Config file** | `pytest.ini` — NEW at repo root: `[pytest]` / `pythonpath = .` / `testpaths = tests` (import mechanics, Pitfall 1) |
| **Quick run command** | `python -m pytest -q` |
| **Full suite command** | `python -m pytest` |
| **Estimated runtime** | ~5 seconds |

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
| 1-01 (planner assigns) | 01 | 1 | HLT-01 | — | /health returns 200 with no auth header (never 401) | unit | `python -m pytest tests/test_health.py -q` | ❌ W0 | ⬜ pending |
| 1-02 (planner assigns) | 01 | 1 | SEC-03 | T-1-01 | non-loopback + no token → refusal, exit != 0, NO token file created | unit | `python -m pytest tests/test_boot.py -q` | ❌ W0 | ⬜ pending |
| 1-03 (planner assigns) | 01 | 1 | SEC-03 | T-1-02 | non-loopback + token present → no refusal; loopback → token generated; notice = D-05 sentence, no token value | unit | `python -m pytest tests/test_boot.py -q` | ❌ W0 | ⬜ pending |
| 1-04 (planner assigns) | 01 | 1 | OPS-02 | — | suite runs green with zero network access (autouse blocker) | infra | `python -m pytest -q` | ❌ W0 | ⬜ pending |
| 1-05 (planner assigns) | 01 | 1 | OPS-01 | — | task registered; service reachable at 127.0.0.1:8000/health | manual | `Start-ScheduledTask -TaskName "gogo API 服务"` then `curl http://127.0.0.1:8000/health` | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pip install "pytest>=8.3"` — no pytest on the machine today (audited)
- [ ] `pytest.ini` — root config with `pythonpath = .`, `testpaths = tests`
- [ ] `tests/conftest.py` — autouse network-block fixture (vibe-astock model) + env-isolation fixture
- [ ] `tests/test_health.py` — HLT-01 contract tests
- [ ] `tests/test_boot.py` — SEC-03/D-03/D-05 pure-function tests

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Task Scheduler auto-start survives a Windows reboot | OPS-01 | Cannot assert OS Task Scheduler / reboot from pytest | Register task via installer, `Start-ScheduledTask -TaskName "gogo API 服务"`, `curl http://127.0.0.1:8000/health` → 200; full reboot test is a user action |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
