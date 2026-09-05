# Phase 2 — UI Review

**Audited:** 2026-09-03
**Baseline:** Abstract 6-pillar standards (no UI-SPEC.md exists for this phase — confirmed absent)
**Scope:** Phase 02 produced zero frontend files (deliverables: `api/state.py`, two-line delta in `api/main.py`, `tests/test_state.py`). Per audit directive, this review audits the API's user-facing surface — response bodies, error-message copy, header conventions, state semantics — and marks pixel-only pillars honestly as N/A instead of fabricating visual findings.
**Screenshots:** Not captured — no browser UI exists (ports 3000/5173/8080 dead; port 8000 serves the resident API only). Live HTTP probes of the resident service were captured instead (text bodies recorded below; .planning/ui-reviews/.gitignore gate executed).

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | Wire copy is precise and contract-exact, but the two 503 details differ by one word and "temporarily" overpromises for permanent file absence |
| 2. Visuals | 3/4 | No pixels exist; structural analog (body/header grammar) is coherent except a dual 404 vocabulary confirmed live |
| 3. Color | N/A | No visual surface in this backend phase — nothing to score |
| 4. Typography | N/A | No rendered text surface in this backend phase — nothing to score |
| 5. Spacing | N/A | No layout surface in this backend phase — nothing to score |
| 6. Experience Design | 3/4 | Failure-state design is exceptional (no bare 500, stale never silent, cold-cache 503); consumer ergonomics lag (no docs, no error codes, no retry hint) |

**Overall: 9/12 over the three applicable pillars** (Copywriting 3 + Visuals 3 + Experience Design 3). Color/Typography/Spacing are excluded as having no subject matter in a pure-API phase; a /24 figure would be meaningless and is not computed. No BLOCKERs found; all findings are WARNING-tier (degrade integration quality, break no user task).

---

## Top 3 Priority Fixes

1. **Add stable machine-readable error codes to the 503/404 bodies** — Today a consumer or operator cannot programmatically distinguish "state file missing" from "transient read failure" or "bad name" from "bad path" without string-matching English prose (`{"detail": ...}` only, api/state.py:87/91/114). Adding a stable `code` field (e.g. `{"detail": "state temporarily unavailable", "code": "state_data_unavailable"}`) makes the contract branchable. Requires user sign-off — D-04 pins the minimal `{"detail": ...}` shape.
2. **Close the dual-404 grammar gap** — Live probe: `GET /v1/state/portfolio` returns `{"detail":"unknown state name"}` while `GET /v1/state/` on the same URL family returns the framework's `{"detail":"Not Found"}`. The consumer contract must either standardize 404 bodies (catch-all 404 exception handler) or explicitly document both vocabularies — the phase's own tests deliberately assert status-only for the framework class (contract design), but that burden is silently passed to every future consumer, starting with the gui_cloud.py HTTP-ification.
3. **Enable a machine-readable or in-repo contract for the public endpoints** — `docs_url=None, redoc_url=None, openapi_url=None` (api/main.py:25, Phase 1 discretion) leaves a public-by-design API with zero discoverability: valid names, header semantics, and the stale/ready contracts live only in `.planning` markdown. Minimum fix: re-enable `openapi_url`, or ship an `api/README.md` stating the exact contract (3 names, X-Data-* headers, stale semantics, cold-start 503 residual).

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

User-facing string inventory (all confirmed live on 127.0.0.1:8000):
- `{"status":"ok","uptime_seconds":N}` (api/main.py:31) and `{"status":"ready"}` (api/state.py:117) — status bodies
- 404 `{"detail":"unknown state name"}` (api/state.py:87)
- 503 `{"detail":"state temporarily unavailable"}` (api/state.py:91)
- 503 `{"detail":"state file unavailable"}` (api/state.py:114, 116)
- Headers `X-Data-Mtime` / `X-Data-Age-S` / `X-Data-Stale: true` (api/state.py:93-97)

**Positives:** ASCII-only, minimal, path-free (no disclosure — D-04 honored); error envelope shape consistent with FastAPI convention; header prefix `X-Data-*` names a coherent family; 404/503 correctly split client vs server error. Tests pin the exact same copy (tests/test_state.py:102, 127, 204, 214, 225, 238) — implementation matches the user-signed contract verbatim.

**Issues (WARNING):**
- **Near-duplicate 503 pair:** "state temporarily unavailable" (data-serving path) vs "state file unavailable" (readiness path) differ by one word and are easily confused during an incident where both endpoints 503 (missing file takes both down). The two failures are semantically distinct (data read failure vs file absence diagnosis) but the copy does not carry that distinction.
- **"temporarily" overpromises:** a permanently missing file (pipeline broken, misconfiguration) yields "temporarily unavailable" indefinitely — the consumer cannot tell a retryable condition from a dead one. 503 status implies retryability, but the wording reinforces a wrong expectation.
- **No stable error identity:** details are prose; any future wording change silently breaks consumers that string-match. Abstract API-copy best practice calls for a stable code alongside human detail.

### Pillar 2: Visuals (3/4)

No pixels, no DOM, no components — this phase has no visual surface in the screen sense. Scored on the closest structural analog: response-body and header grammar consistency.

**Positives:** Three body grammars exist but are each internally consistent and semantically motivated — verbatim raw bytes for state payloads (deliberately un-enveloped, D-01), minimal `{"status": ...}` for health/readiness, `{"detail": ...}` for errors. Header metadata consistently grouped under `X-Data-*`; content-type exactly `application/json` with no charset (live-verified); CRLF preserved on the wire (probe head: `{\r\n  "date": "2026-09-02"...`).

**Issue (WARNING):** Dual 404 vocabulary (live-confirmed): route-matching whitelist miss returns the handler's `{"detail":"unknown state name"}`, route-non-match returns the framework's `{"detail":"Not Found"}`. Same status class, two body shapes, on the same URL family — a presentation inconsistency in the wire contract that the phase's tests knowingly leave unpinned (test class (b) asserts status-only per plan).

### Pillar 3: Color (N/A)

No visual surface — no colors, no 60/30/10 distribution, no hardcoded hex. Scoring this pillar would require fabricating findings; nothing to audit in a pure HTTP API deliverable.

### Pillar 4: Typography (N/A)

No rendered text, no font sizes/weights, no hierarchy. The only text-adjacent discipline present is encoding hygiene (ASCII console text per api/main.py:8; binary/CRLF byte preservation per api/state.py:45-48) — that is data fidelity, not typography.

### Pillar 5: Spacing (N/A)

No layout surface, no spacing scale. JSON indentation is deliberately the pipeline writer's own (byte-verbatim contract, D-01/D-02) — the API must not normalize it, and it doesn't.

### Pillar 6: Experience Design (3/4)

Scored on state coverage and interaction semantics of the HTTP surface.

**Positives (genuinely strong — this is the phase's core deliverable):**
- **Never a bare 500:** cold-cache/unavailable data yields 503 (api/state.py:91), decode-failure with warm cache yields flagged stale 200 (api/state.py:96-97) — every failure has a designed, tested representation (16-test suite incl. threaded truncate/atomic-rewrite hammer; tests/test_state.py).
- **Stale is never silent:** `X-Data-Stale: true` appears only on the fallback path, and stale responses carry the cached payload's own mtime (state.py:93-97) so body and headers always describe the same version — headers never lie about served bytes.
- **Ready semantics decoupled from data age:** /health/ready answers 200 for ancient mtime by design (HLT-02); OSError skips retries (deterministic per-request); client/server error split (404/503) is textbook.

**Issues (WARNING):**
- **Zero discoverability:** openapi/docs disabled (api/main.py:25) while /v1/state/* is public by design — the stated consumer (cloud panel, INTEGRATIONS.md) must read `.planning` markdown to learn names, headers, and stale semantics. No `Retry-After` on 503s, no valid-name enumeration on 404, no error codes (see Top 3).
- **First-poll wrinkle:** the documented cold-start 503 residual (restart coinciding with a write window) means a polling consumer can see one 503 after restart before warming — acceptable and documented internally, but nothing on the wire tells the consumer this is transient-and-expected vs broken.
- **Stale-200 trust boundary:** a naive consumer that ignores `X-Data-Stale` treats a stale payload as fresh (it is a 200 with valid JSON). The header contract is correct, but nothing enforces consumer-side honoring of it.
- **Semantics trap:** "ready 200 + large X-Data-Age-S" is the intended signal for "service healthy, data old" — but it requires consumers to combine two endpoints and reason about a combination that looks contradictory at first glance. Worth an explicit consumer-facing note wherever the contract is documented.

---

## Registry Safety Audit

`components.json` does not exist (no shadcn); UI-SPEC.md absent. **Skipped — not applicable to a backend phase with zero frontend dependencies** (zero new packages this phase, per SUMMARY).

---

## Files Audited

- `api/state.py` — read in full (118 lines): all user-facing copy, headers, and state semantics audited above
- `api/main.py` — read in full (77 lines): /health body, docs-disabled decision (line 25), router registration
- `tests/test_state.py` — 16 test functions confirmed; copy-pin assertions verified at lines 102/127/204/214/225/238
- Live HTTP surface probed on 127.0.0.1:8000 (resident service running Phase 2 code): /health, /health/ready, /v1/state/market_state (headers + CRLF body head), /v1/state/portfolio 404, /v1/state/ 404
- `.planning/phases/02-read-only-state-endpoints-defensive-read-layer/02-01-SUMMARY.md`, `02-01-PLAN.md`, `02-CONTEXT.md` (contract context)

---

## Notes on Classification

- **BLOCKERs:** none. Every contract test passes; the served surface matches the user-signed D-01..D-05 decisions exactly; no user task is broken.
- **WARNINGs (3 priority fixes above):** all three are consumer-ergonomics gaps on a surface that has no consumer wired to it yet — the cheapest moment to fix them is before gui_cloud.py (or any external script) integrates against the raw-body contract, because D-01 makes the body shape one-way.
- **Changes to the wire contract** (codes field, wording, docs on/off) touch user-signed decisions (D-04 minimal detail) — any adoption of the recommendations above requires user confirmation per the project's 定稿机制.
