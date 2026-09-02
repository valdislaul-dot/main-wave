---
phase: 1
slug: service-skeleton-health-liveness
audited: 2026-09-03
baseline: abstract-6-pillar (no UI-SPEC)
overall: 23/24
pillars:
  copywriting: 4
  visuals: 4
  color: 4
  typography: 4
  spacing: 4
  experience: 3
---

# Phase 1 — UI Review (Service Skeleton + /health Liveness)

**Audited:** 2026-09-03
**Baseline:** Abstract 6-pillar standards (no UI-SPEC.md exists anywhere in `.planning`)
**Nature of this phase:** Headless JSON service by design — the "user-facing surface" is a JSON endpoint, console/boot message surface, a log file, and two operator scripts. Pillars 2–5 scored on the nearest existing surface with grep-verified absence as evidence.

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 4/4 | Every console/JSON string deliberate, contract-pinned, ASCII; zero generic labels |
| 2. Visuals | 4/4 | No visual UI by design; JSON document flat, 2 keys, stable order, exact bytes |
| 3. Color | 4/4 | Zero color references in any phase file (grep-verified); no surface to violate |
| 4. Typography | 4/4 | No font surface; ASCII-only discipline in all console-facing files (GBK-safe) |
| 5. Spacing | 4/4 | No spacing scale surface; compact JSON, single-line token file, 5-line bat |
| 6. Experience Design | 3/4 | States well covered; deductions: resident service was down at audit time + installer destructive ordering gap |

**Overall: 23/24**

## Top 3 Priority Fixes

1. **Restart the resident service — liveness contract was dark at audit time.** `logs/api/console.log` ended with `^C` and no LISTENING process on port 8000. RESOLVED 2026-09-03 by orchestrator: `Start-ScheduledTask -TaskName gogo-api` → probe 200 `{"status":"ok","uptime_seconds":7}`, task State Running.
2. **Installer unregisters the existing task before the new one exists** (`scripts/daily/install_api_task.ps1:21`, `Unregister-ScheduledTask -Confirm:$false` first): a mid-run registration failure leaves zero autostart. Suggested fix: `Register-ScheduledTask -Force` overwrites in place, or announce "Replacing existing task gogo-api" before the destructive unregister. Deferred to Phase 5 hardening (with WR-03).
3. **Machine state vs phase record drift** — record the interrupt cause in 01-02-SUMMARY.md outcome slot: service restarted via scheduled task 2026-09-03 (orchestrator action), backstop reboot check completed as UAT test 1 (pass).

## Detailed Findings

### Pillar 1: Copywriting (4/4)
- `/health` body contract-exact (`{"status":"ok","uptime_seconds":N}`), key names self-documenting, pinned by tests.
- SEC-03 refusal copy names the bound host and the remedy (env var + file path), ASCII-only, non-zero exit.
- D-05 notice is the sole stdout of the generation path, never carries the token value.
- Installer transcript echoes resolved paths and the next command.
- Minor (no score impact): port-parse error could echo the received value.

### Pillar 2: Visuals (4/4)
No visual UI by explicit design. Nearest surface (response document): flat 2-key JSON, stable order, no BOM. console.log stays readable (access_log=False).

### Pillar 3: Color (4/4)
Grep for hex colors / rgb( / CSS / class= across all phase files: 0 hits.

### Pillar 4: Typography (4/4)
run_api.bat + install_api_task.ps1 ASCII-verified; all print() strings ASCII (GBK-console guarantee).

### Pillar 5: Spacing (4/4)
JSON compact (content-length 34); token file single-line; D-05 notice one sentence; run_api.bat exactly 5 lines.

### Pillar 6: Experience Design (3/4)
- Error states: SEC-03 actionable + no token file (Pitfall-2 pinned); port-parse exits 1; bind failures land in console.log + LastTaskResult.
- Degenerate states: empty env token / empty token file / unreadable file / empty host all fail closed toward refusal.
- Warnings: (1) resident service was down at audit time — RESOLVED by orchestrator restart; (2) installer destructive ordering gap — deferred to Phase 5.

## Minor Recommendations
- Echo the offending value in the port-parse error (`api/main.py:45`)
- Consider `Cache-Control: no-store` on `/health` for proxy hygiene
- Pillars 2–5 scored on a no-presentation-surface phase; grep-verified absence is the evidence

## Files Audited
api/main.py · api/boot.py · run_api.bat · scripts/daily/install_api_task.ps1 · tests/test_health.py · tests/test_boot.py · logs/api/console.log (tail) · live probe on 8017 · 01-01/01-02 SUMMARY + PLAN + 01-CONTEXT.md
