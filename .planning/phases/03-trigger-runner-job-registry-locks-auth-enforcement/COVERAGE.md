# API Coverage — Phase 3

No external API integration: this phase *exposes* a local HTTP surface (`POST /v1/actions/{kind}`, `GET /v1/jobs/{job_id}`) on the already-running FastAPI service and spawns four existing in-repo pipeline scripts as local subprocesses (arg-list, stdlib `subprocess.Popen`). Every capability it touches is either in-repo code or a local child process — it consumes no third-party API/SDK/service, and the stack stays stdlib-only (RESEARCH Package Legitimacy Audit: zero installs).
