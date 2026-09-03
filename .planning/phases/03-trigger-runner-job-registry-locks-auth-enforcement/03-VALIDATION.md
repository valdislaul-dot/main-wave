---
phase: "03"
slug: "trigger-runner-job-registry-locks-auth-enforcement"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-04"
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pythonpath=., testpaths=tests) on Python 3.13.1 |
| **Config file** | pytest.ini (no plugin config needed) |
| **Quick run command** | `python -m pytest tests/test_actions.py tests/test_auth.py tests/test_jobs.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~3 seconds (baseline 58 passed, 1 skipped in 2.26s) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_actions.py tests/test_auth.py tests/test_jobs.py -q`
- **After every plan wave:** Run `python -m pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD (plan pending) | TBD | TBD | ACT-01 | — | 四种 kind 以固定 arg-list spawn 正确脚本（无 shell），202+job_id 立即返回，log path 存在 | unit/integration (fake scripts in tmp_path) | `pytest tests/test_actions.py -x` | ❌ W0 | ⬜ pending |
| TBD (plan pending) | TBD | TBD | ACT-02 | — | job 生命周期 pending→running→succeeded/failed；exit 0 vs non-0；未知 id 404；log path 在响应体 | unit/integration | `pytest tests/test_actions.py -x` | ❌ W0 | ⬜ pending |
| TBD (plan pending) | TBD | TBD | ACT-03 | — | 重叠→409+运行中 job_id；完成后重触发→202；跨进程锁（独立进程持有锁）→409；持有者被杀后→202 | unit/integration (real cross-process lock) | `pytest tests/test_actions.py -x` | ❌ W0 | ⬜ pending |
| TBD (plan pending) | TBD | TBD | SEC-01 | T-01 | 缺失 key→401+WWW-Authenticate；错误→403；有效→202；公开端点（health/ready/state）豁免；401/403 不 spawn 进程；token 值不进 job logs/console.log | unit/integration | `pytest tests/test_auth.py -x` | ❌ W0 | ⬜ pending |
| TBD (plan pending) | TBD | TBD | ACT-02 (SC5) | — | reload_registry：fixture registry 中 pending/running 文件→interrupted 终态；修剪封顶 ≤500；模拟重启后 GET 可查 | unit (pure function on tmp_path) | `pytest tests/test_jobs.py -x` | ❌ W0 | ⬜ pending |
| TBD (plan pending) | TBD | TBD | SC3 | — | 真实（fake long-sleep）job 运行中 GET /health 持续应答，P95 < 50 ms | smoke/perf | `pytest tests/test_jobs.py::test_health_latency_during_job -x` + live verify | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_actions.py` — covers ACT-01/02/03 contract (fake scripts, cross-process lock child)
- [ ] `tests/test_auth.py` — covers SEC-01 (401/403/exemptions/spawn-block/no-leak grep)
- [ ] `tests/test_jobs.py` — covers registry transitions, reload sweep (SC5), pruning cap, /health latency during job
- [ ] `tests/conftest.py` — optional additions: tmp token-file helper; `api.jobs.JOBS_DIR`/`LOCK_DIR` monkeypatch helpers (existing network-block + env-clean fixtures are reused as-is)
- [ ] No framework install needed (pytest present, baseline green)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SC5 真机重启恢复 | ACT-02 | TestClient 无法覆盖真实进程 kill/重启生命周期 | 经 API 启动真 pipeline job → `taskkill /F /T` API 进程 → 重启 → GET /v1/jobs/{id} 显示 interrupted 终态 |
| SC1–SC4 真机冒烟 | ACT-01/02/03/SEC-01 | 真管线/真锁/真密钥行为需在真机验证 | 按 5 条成功标准逐条冒烟（202+job_id / 409 / P95<50ms / 401-403 / 密钥不泄露） |
| 停用 15:30 计划任务 (D-02) | 运维 (CONTEXT D-02) | 需提权 PowerShell，不可自动化 | 提权 PowerShell 执行 `Unregister-ScheduledTask -TaskName "主升浪每日选股流水线" -Confirm:$false` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
