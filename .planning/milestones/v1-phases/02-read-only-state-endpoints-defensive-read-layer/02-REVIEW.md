---
phase: 02-read-only-state-endpoints-defensive-read-layer
reviewed: 2026-09-03T12:19:34Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - api/main.py
  - api/state.py
  - tests/test_state.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-09-03T12:19:34Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Reviewed the Phase 2 read-only state endpoints implementation (`api/state.py` defensive read layer + route registration in `api/main.py`) and its contract suite (`tests/test_state.py`), at standard depth with cross-file tracing into `api/boot.py`, `scripts/daily/config.py`, and `tests/conftest.py`.

The core implementation is sound and matches its documented contract (D-01..D-05, STA-01/STA-03/HLT-02): whitelist check precedes any path composition, byte-verbatim passthrough with same-handle fstat mtime, decode-retry then stale-cache fallback with coherent body/header versioning, cold-cache 503, and stat-only readiness. Live probes on a real uvicorn server confirmed byte-identical serving, exact headers, and 404/503 behavior; full suite passes (34 passed, 1 skipped). No blocker found.

The defects found are concentrated in test fidelity (two warnings: a contract pin that only holds under the test client, and a hammer that can pass vacuously) plus one security-gap warning on the boot token gate that this phase's public routes ride on. Four info items document edge contracts that are unenforced or under-documented.

Verified empirically during review: full suite green; live uvicorn probe on a spare port confirmed `/v1/state/auction_state` 200 byte-verbatim, and that a raw dot-segment URL (`/v1/state/market_state/../auction_state` sent with `--path-as-is`) returns framework 404, not the 200 the test suite pins.

## Warnings

### WR-01: SEC-03 token gate is presence-only and self-opening; state routes ride it unauthenticated

**File:** `api/main.py:53-68` (and `api/boot.py:36-47`), route surface at `api/state.py:83-100`
**Issue:** The non-loopback bind gate (`if not is_loopback(host)`) only checks that a token *exists* (`has_token(token_path)`); nothing ever authenticates requests against it — no middleware, no dependency, no header check (explicitly documented at `api/main.py:24-25`). Two consequences compound: (1) the token is a boot tripwire only, and (2) the tripwire auto-opens: any default loopback run calls `ensure_token` (`api/main.py:66-68`), which permanently writes `data/api_token.txt` via `boot.ensure_token` (D-03). From that moment on, an accidental `GOGO_API_HOST=0.0.0.0` run passes the SEC-03 gate silently (no console notice in the non-loopback branch) and serves `/v1/state/*` and `/health/ready` to the LAN with no credential check and no log signal. The fail-closed branch is therefore reachable only on a machine that has never booted the API once.
**Fix:** For non-loopback binds, require an explicitly supplied credential (env `GOGO_API_TOKEN` only, or a startup confirmation) instead of file presence — the file can no longer distinguish deliberate exposure from accidental exposure once auto-generated. At minimum, print a prominent console warning on non-loopback binds stating that routes are unauthenticated until SEC-02 lands (Phase 4 owns classification of these routes, but the gap is real today and this phase ships the public surface).

### WR-02: Rewrite hammer can pass vacuously — writer-thread exceptions are swallowed and no rewrite progress is asserted

**File:** `tests/test_state.py:290-330`
**Issue:** `writer_loop` (lines 290-315) is started as a daemon-less thread whose body has no try/except beyond the `os.replace` OSError catch. Any unexpected exception (e.g., `PermissionError` on `open(path, "wb")` from an AV lock) kills the thread silently — threading only prints to stderr. The test then still passes: files remain at the good fixture content, all ~150 GETs return fresh 200 with parseable bodies, and the `x-data-stale` branch (line 325-326) is simply never exercised. There is also no assertion that the writer completed even one full rewrite iteration or that any request overlapped a torn window, so the "0 x 5xx under active rewrite" property can be "verified" without a single torn read ever occurring.
**Fix:** Capture exceptions inside `writer_loop` into a shared slot (e.g., `errors.append(traceback)`) and `raise`/assert after `join`; add a `progress` counter incremented per completed iteration and assert `progress >= 1` (ideally with a small barrier or initial-sleep so the writer is mid-loop when the GET burst starts). This makes the hammer fail loudly instead of degrading to a static-file smoke test.

### WR-03: Dot-segment contract pin (200) reflects httpx TestClient URL normalization, not server behavior — live uvicorn returns 404

**File:** `tests/test_state.py:111-115`
**Issue:** The test asserts `/v1/state/market_state/../auction_state` → 200 served as the resolved whitelisted name, and the plan documents this as "dot-segment removal happens before routing". Verified against a real uvicorn server (curl `--path-as-is`): the raw path never matches the route regex and returns the framework's 404 `{"detail": "Not Found"}` — the handler never runs. The 200 in the suite is produced by httpx (TestClient) collapsing `..` client-side *before* the request reaches the ASGI app; no normalization exists in the deployed routing path. Both outcomes are safe (404 is stricter), but the suite pins a behavior the shipped server does not have, misdocumenting the wire contract for Phase 3 consumers, and would go green even if server-side dot-segment handling changed meaningfully.
**Fix:** Change class (c) to assert the real behavior — 404 for the raw dot-segment URL when the path is not client-normalized — and/or explicitly comment that the 200 variant only holds because httpx normalizes the URL before transport. If the intent is to guarantee alias URLs resolve, add a server-side normalization test via a raw ASGI scope request instead of the httpx client.

## Info

### IN-01: `get_state` has no whitelist guard of its own; reader-contract violations escape as raw 500

**File:** `api/state.py:66`, `api/state.py:72`
**Issue:** `STATE_FILES[name]` at line 66 raises `KeyError` for any name not in the map — only the endpoint's pre-check (line 86) protects it; a future caller (Phase 3 trigger tooling is the stated consumer of this seam) gets an uncaught KeyError. Relatedly, the retry classification `except (ValueError, UnicodeDecodeError)` does not cover `TypeError`: a reader returning `None` makes `json.loads(None)` raise `TypeError`, which propagates uncaught to a bare 500 — the one outcome the module exists to prevent.
**Fix:** Raise `StateUnavailable` (or a `ValueError` with the name) when `name not in STATE_FILES` inside `get_state`, and narrow the reader contract by validating the return type before `json.loads` (or widen the retry tuple consciously with a comment).

### IN-02: `os.access(path, os.R_OK)` is near-equivalent to existence on Windows — the "unreadable" leg of `/health/ready` is inert on the primary platform

**File:** `api/state.py:113`
**Issue:** On Windows, the CRT `access()` that backs `os.access` grants R_OK to any existing file regardless of ACL or lock state (the read-only attribute is only enforced for W_OK). The resident service runs on Windows (scheduled task, `run_api.bat`); there, ready() 503s only for missing files or directory-typed entries, and can answer 200 "ready" for a file that the read layer would serve stale/503 (e.g., an exclusively locked file). The suite's chmod leg is silently skipped on Windows (test line 240-248), so nothing pins this gap.
**Fix:** Document the Windows semantics in the ready() docstring, or probe readability with an actual open+close handle (the Pitfall-2 concern applies to *held* handles; an immediate open/close probe per request is the same window the read layer already opens) — or accept and pin that on Windows ready() means existence only.

### IN-03: Freshness-critical responses carry no Cache-Control header

**File:** `api/state.py:92-100`
**Issue:** The endpoint's entire purpose is serving time-varying state with explicit freshness headers, but responses set no `Cache-Control`. RFC 7234 heuristic freshness requires `Last-Modified`, which is absent, so well-behaved caches refetch — but any intermediary that stores responses without validators can replay a body without the consumer's freshness machinery having run, silently defeating X-Data-Stale semantics for a polling consumer behind a proxy (the Phase 3 cloud-panel deployment direction).
**Fix:** Add `"Cache-Control": "no-store"` (or `max-age=0, must-revalidate`) to the response headers — one line, removes the ambiguity for any future intermediary.

### IN-04: Validation gate cannot detect torn-but-valid JSON prefixes; hammer never exercises the case

**File:** `api/state.py:48`, `tests/test_state.py:297-304`
**Issue:** The guard "torn file never served fresh" is only as strong as `json.loads`: a truncate-writer that stops exactly at a JSON document boundary (valid prefix of a longer document) passes validation and is served fresh with the torn mtime. The hammer deliberately cuts at the last closing brace (`good.index(b"}")`, line 300-301) so every tear is syntactically invalid — the prefix-valid tear class is untested. This is inherent to validate-then-serve (the signed D-01..D-05 contract), but it is a real boundary of the guarantee that the docstrings currently present as absolute ("撕裂绝不新鲜出网").
**Fix:** Add one docstring sentence stating the guarantee is syntactic (decode-level) only — a semantically truncated but valid-JSON document cannot be distinguished — so Phase 3 consumers know to treat body-end markers/consumers-side checks as out of contract.

---

_Reviewed: 2026-09-03T12:19:34Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
