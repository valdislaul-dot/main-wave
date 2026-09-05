---
phase: 01-service-skeleton-health-liveness
reviewed: 2026-09-02T23:02:32Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - .gitignore
  - api/__init__.py
  - api/boot.py
  - api/main.py
  - pytest.ini
  - requirements.txt
  - run_api.bat
  - scripts/daily/install_api_task.ps1
  - tests/conftest.py
  - tests/test_boot.py
  - tests/test_health.py
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 1: Code Review Report

**Reviewed:** 2026-09-02T23:02:32Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the service-skeleton phase: FastAPI `/health` liveness app (`api/main.py`),
pure-function boot/token layer (`api/boot.py`), Windows launcher and scheduled-task
installer, and the pytest suite (run locally: 18 passed, 1 skipped).

Overall structure is sound and the code honors its own discipline well: fail-closed
loopback detection, env-over-file token priority, lazy uvicorn import, ASCII-only
console text, and correct Pitfall-2 ordering (non-loopback refusal branch never
generates a token) are all implemented as specified and verified by tests. The
PowerShell object semantics in `install_api_task.ps1` (`$Trigger.Delay = 'PT5M'`,
`ExecutionTimeLimit` PT0S, Interactive principal) were empirically validated on this
machine and are correct.

Findings concentrate on four areas: (1) the SEC-03 gate is a start-time intent check
that D-03 auto-generation permanently disarms, with no per-request enforcement;
(2) missing validation of `GOGO_API_HOST`/`GOGO_API_PORT` values that fail late at
bind time; (3) `install_api_task.ps1` masks its own failures (non-elevated runs exit 0
with a success message — the exact failure its header documents); (4) `import api.main`
carries a filesystem-write side effect through `scripts/daily/config.py`, contradicting
the phase's documented Pitfall-3 import-purity contract.

## Warnings

### WR-01: SEC-03 gate is permanently disarmed by D-03 auto-generation; token never authenticates anything

**File:** `api/main.py:49-64` (also `api/boot.py:55-77`)
**Issue:** The non-loopback branch refuses to start only when no token exists, and no
code anywhere validates the token against requests — the gate is a start-time intent
check. Worse, the D-03 auto-generation in the loopback branch makes the gate
one-time-only: on this machine `data/api_token.txt` already exists (auto-created by
the E2E loopback boot, Sep 3 06:23), so any later start with `GOGO_API_HOST=0.0.0.0`
sails through silently. There is no re-arm path short of manually deleting the file,
so the "operator consciously authorized remote binding" signal the gate is meant to
provide is consumed on first loopback run and never restored. Exposure today is
limited to `/health` (which must stay anonymous per HLT-01), so this is not exploitable
now — but the control will be illusory the moment a stateful endpoint is added.
**Fix:** When protected endpoints are added, enforce the token per-request via
FastAPI dependency/middleware with `/health` exempted (Pitfall 6). Until then, either
log a notice at non-loopback start when the token file was auto-generated (so the
operator is aware remote binding is permitted by a file they never consciously
created), or separate "operator configured token" from "auto-generated token"
(e.g., refuse non-loopback binds when only an auto-generated file exists).

### WR-02: No range/format validation for GOGO_API_PORT; host not normalized

**File:** `api/main.py:41-46`
**Issue:** Only `ValueError` from `int()` is caught. `GOGO_API_PORT=0` passes and
uvicorn silently binds an OS-assigned ephemeral port (service "runs" but the health
endpoint is not on the documented 8000); `-1` or `70000` pass parsing and die later
with an unhandled traceback inside uvicorn instead of a clean startup error. `host`
is never stripped or validated: `GOGO_API_HOST="127.0.0.1 "` (trailing space, verified)
fails `is_loopback` (fail-closed, token required) and then reaches uvicorn's bind
unnormalized, producing a late crash whose behavior depends on the platform resolver.
**Fix:**
```python
host = os.environ.get("GOGO_API_HOST", "127.0.0.1").strip()
try:
    port = int(os.environ.get("GOGO_API_PORT", "8000"))
    if not (1 <= port <= 65535):
        raise ValueError
except ValueError:
    print("ERROR: GOGO_API_PORT must be an integer in 1..65535", file=sys.stderr)
    sys.exit(1)
```

### WR-03: install_api_task.ps1 reports success and exits 0 on failure

**File:** `scripts/daily/install_api_task.ps1:48-57`
**Issue:** There is no `$ErrorActionPreference = 'Stop'` and `Register-ScheduledTask`
has no `-ErrorAction Stop`. Cmdlet errors are non-terminating in PS 5.1, so the exact
failure mode the file's own header documents — non-elevated run denied with
0x80070005 — still falls through to `Write-Output "Registered task: gogo-api ..."`
and exit code 0. Any caller (or the user) sees a success message for a task that was
never registered. The `try/catch` on line 21 only wraps the unregister step.
**Fix:**
```powershell
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Must run from an ELEVATED PowerShell (Register-ScheduledTask in root folder is denied otherwise, 0x80070005)"
    exit 1
}
if (-not (Test-Path -LiteralPath $BatPath)) {
    Write-Error "run_api.bat not found at $BatPath"
    exit 1
}
try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
} catch {}
try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger1 `
        -Settings $Settings -Principal $Principal -Description "..." -Force
} catch {
    Write-Error $_
    exit 1
}
```

### WR-04: `import api.main` has a filesystem-write side effect via scripts/daily/config.py, contradicting the documented Pitfall-3 purity contract

**File:** `api/main.py:16` -> `scripts/daily/config.py:13-14`
**Issue:** `api/main.py`'s module docstring asserts "模块导入必须无副作用 ... 这样测试
(TestClient) 可以安全地 import api.main", and `tests/test_health.py` pins that claim.
But the import chain executes `os.makedirs(DATA_DIR, DAILY_DIR, LOG_DIR, KLINE_DIR)`
at import time in `scripts/daily/config.py`. Verified: a fresh clone tracks zero files
under `data/daily_close/`, `data/kline_data/`, and `logs/`, so a clean checkout or CI
import recreates four directories as a side effect of importing the module — and on a
read-only checkout (immutable deploy, USB media) the import itself raises, killing the
service before `main()` can produce a clean error. The purity guarantee the tests
assert is narrower than the contract the docstring states.
**Fix:** Move the directory bootstrap into an explicit function in
`scripts/daily/config.py` (e.g., `ensure_dirs()`), called from entry-points
(`run_pipeline.py`, GUI, `api.main.main()`), not at module import — or, if the
import-time bootstrap must stay for the legacy scripts, document the exception in the
api module docstring and adjust the test story accordingly.

## Info

### IN-01: Token file is created with permissive ACL (0644)

**File:** `api/boot.py:75-76`
**Issue:** `data/api_token.txt` is written with default permissions (observed
`-rw-r--r--`, readable by all local users). Harmless while the token gates nothing,
but it is a bearer credential for future endpoints. Tighten now or when auth lands:
`os.chmod(token_path, 0o600)` after write (Windows: equivalent via `icacls` or the
default ACL of the repo dir).

### IN-02: `_no_network` fixture guarantee is narrower than claimed

**File:** `tests/conftest.py:31-48`
**Issue:** Only `socket.socket.connect` is patched. Outbound attempts via
`socket.connect_ex` (used by `SelectorEventLoop`/`loop.sock_connect`) and via Windows
asyncio `ProactorEventLoop` (overlapped ConnectEx — no Python-level `connect` call at
all) bypass the guard, so the "套件级保证: 测试零外部网络访问" claim does not hold for
asyncio-based code paths on this platform. Also, the `host == "localhost"` allowance
is case-sensitive while `is_loopback` lowercases. No current test exercises these
paths, so this is latent — but future tests that exercise data-source code (requests
over anyio/httpx async) must not rely on this fixture to block the network.
**Fix (when needed):** additionally patch `socket.socket.connect_ex` and
`socket.create_connection`, or use pytest-socket / a session-level DNS block.

### IN-03: Import-purity test silently skips in the steady state

**File:** `tests/test_health.py:46-52`
**Issue:** `test_import_api_main_creates_no_token_file` skips whenever the real
`data/api_token.txt` exists — which is the steady state on this machine after the E2E
loopback boot (confirmed: the test was skipped in the local run). The no-side-effect
assertion is therefore dormant in exactly the environment where it would catch
regressions. `tests/test_boot.py` already demonstrates the better pattern:
monkeypatch `api.main.DATA_DIR` to a `tmp_path` and assert against that.

### IN-04: Scheduled task with Interactive logon type does not run at boot without a logon

**File:** `scripts/daily/install_api_task.ps1:45-46, 56`
**Issue:** With `-LogonType Interactive`, the AtStartup trigger only fires once the
user has an interactive session; on a boot that lands on the lock screen or with no
logon, the service starts at first logon rather than "about 5 minutes after system
startup" as the comment and output claim. This is a reasonable trade-off (no stored
password, Limited privilege), but the description should state "at first logon after
boot" so a later "service did not start" investigation is not a surprise.

### IN-05: D-05 notice hardcodes the token path while the code derives it from DATA_DIR

**File:** `api/main.py:64`
**Issue:** The notice prints `data/api_token.txt` literally even though `token_path`
is `os.path.join(DATA_DIR, "api_token.txt")` (line 47). The message is wrong if
`DATA_DIR` is ever reconfigured, and `tests/test_boot.py:124` pins the literal string,
so the inconsistency is baked into the contract. Cosmetic today; prefer printing the
actual `token_path` (and relaxing the test assertion to match) or documenting that
the literal is intentional.

---

_Reviewed: 2026-09-02T23:02:32Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
