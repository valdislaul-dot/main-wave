---
phase: "2"
slug: "read-only-state-endpoints-defensive-read-layer"
status: verified
threats_open: 0
asvs_level: 1
created: "2026-09-03"
---

# Phase 2 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Probe client → GET handlers | Only input is the `{name}` path parameter; whitelist resolution decides whether a request reaches the filesystem at all | path parameter (untrusted) |
| data/ filesystem → read layer | Files written by separate pipeline processes (atomic os.replace and direct truncate-writers); content crosses into the API process untrusted and possibly mid-write | state JSON (untrusted, possibly torn) |
| Read layer → consumer | Served bytes + freshness headers + (fallback only) stale flag become the consumer's view of trading state | response body + headers |
| In-process cache → handlers | `_CACHE` holds last-good payload per name; process-local, cold after restart by design | cached bytes (last-known-good) |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-02-01 | Information Disclosure | /v1/state/{name} path resolution | high | mitigate | D-03 fixed 3-name dict lookup before any os.path.join; contract tests pin whitelist 404 matrix + traversal-shaped URL classes | closed |
| T-02-02 | Tampering | Torn/half-written JSON served as fresh | high | mitigate | Validate-then-serve (json.loads on exact bytes) + 2×~20ms short retry + last-good cache with X-Data-Stale:true; cold cache 503; pinned by tests 5-10 + rewrite hammer | closed |
| T-02-03 | Elevation of Privilege / Information Disclosure | Outbound network call from a GET handler | high | mitigate | Triple-layer SC4: import restriction (only scripts.daily.config), standalone grep audit (empty output verified), in-suite source-scan test + conftest net-block | closed |
| T-02-04 | Information Disclosure | Error bodies | medium | mitigate | D-04 minimal {"detail": ...} strings; test 4 asserts no path/separators in 503 body | closed |
| T-02-05 | Denial of Service / Tampering (adjacent system) | Reader handle blocking pipeline's atomic os.replace | medium | mitigate | open→read→fstat→close per attempt, no handle across retries; no FileResponse; hammer exercises os.replace under load | closed |
| T-02-06 | Tampering | Body/mtime mismatch (headers lie about served version) | medium | mitigate | X-Data-Mtime from os.fstat on the very handle read; stale responses carry cached payload's stored mtime; tests 1/9 assert coherence | closed |
| T-02-07 | Tampering | Response header injection | low | mitigate | Header values derive exclusively from integers via str(); exact-header tests pin shape | closed |
| T-02-08 | Denial of Service | Unbounded read of huge files | low | accept | Producer-owned bounded state (≤48 KB today, single-user loopback); revisit in Phase 4 hardening | closed |

*Status: open · closed · open — below {block_on} threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-02-01 | T-02-08 | Served files are producer-owned bounded state (≤48 KB, single-user loopback service); a byte cap would be speculative — revisit if file sizes or deployment change (Phase 4 hardening note) | plan-time disposition | 2026-09-03 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-03 | 8 | 8 | 0 | gsd (L1 grep-depth, short-circuit) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-03 — 8/8 closed (7 mitigate verified against green contract tests + live probes, 1 documented accept).
