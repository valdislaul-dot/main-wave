# Phase 4: Exposure Hardening + Data Classification - Context

**Gathered:** 2026-09-04
**Status:** Ready for planning

<domain>
## Phase Boundary

gogo 最敏感的数据——持仓/账本/候选——通过 token 门控端点对外服务，分级政策明确文档化；整个暴露面（bind、日志、错误、参数、git）硬化，使 2026-08-31 隐私红线在 API 离开 127.0.0.1 时依然成立。

**In scope:** STA-02（持仓/账本/候选读取，独立命名空间 /v1/private/*，token 门控，raw 透传 + 新鲜度头复用防御读层）、SEC-02（数据分级鉴权：公开级 vs 机密级，分级表定稿）、写侧原子化（D-04..D-06：save_portfolio/save_journal tmp+os.replace，STA-02 上线前置）、WR-01 启动级鉴权修复（D-12：env 强制 token + 控制台警告）、触发 date 白名单参数（D-09/SC4）、P2 遗留 WR-02/WR-03 + 错误码归一 + openapi/README 契约、PROJECT.md 分级政策措辞修订（用户已 sign-off，2026-09-04）。

**Not this phase:** job 取消 taskkill 树杀（ACT-04 v2）、孤儿任务收养（ACT-05 v2）、日志轮转/health/details（OPS-03, Phase 5）、ETag/限流/CORS（v2/OOS）、GUI 修复（GUI 已弃用 2026-09-04，零工作项）、PUT/PATCH 状态改写（定稿机制排除）。

**Success criteria** (from ROADMAP.md, must all be TRUE):
1. Consumer with a valid key GETs the 持仓/账本/候选 read endpoints and receives raw file bodies + freshness headers like the public endpoints; without a key they get 401/403. Market/temperature endpoints remain open with no key required.
2. A route-by-route audit shows every endpoint carries exactly its data class's protection — no sensitive route reachable without a token, no public route requiring one; the fail-closed boot check is covered by a test, not just documentation.
3. Error responses expose no file paths or stack traces (details stay in server logs) and no log line contains an Authorization header or token value.
4. Trigger date parameters accept only whitelisted formats (YYYY-MM-DD / YYYYMMDD) and reach scripts as argument lists — shell injection attempts are structurally impossible.
5. Scans confirm data/api_token.txt appears in neither git history nor the sync_cloud whitelist; README documents the API's known limits (single-flight scope, remaining concurrent entry points).
</domain>

<decisions>
## Implementation Decisions

### 敏感端点形态（STA-02 接口契约）
- **D-13:** 端点路径：独立命名空间 `GET /v1/private/{name}`，name ∈ {portfolio, journal, candidates}——与公开 `/v1/state/` 结构性隔离；route-by-route 分级审计（SC2）逐路由可证；鉴权配置失误不会让敏感数据滑入公开命名空间。
- **D-14:** 「候选」语义：无参返回最新一份 candidates_*.json；可选 `?date=` 白名单参数（YYYY-MM-DD / YYYYMMDD）取历史。
- **D-15:** 未授权返回：沿用 D-10 分工——缺头 401 + WWW-Authenticate，错误 key 403；不引入 404 混淆防探测（单用户工具非刚需）。
- **D-16:** 响应体契约：与 STA-01 相同——raw file body + X-Data-Mtime/X-Data-Age-S 头，复用防御式读层；写侧原子化（D-06）为上线前置。
- **D-17:** 承接自 P3：写侧原子化改造仅 save_portfolio + save_journal 两函数，照 `scripts/daily/zt_pool.py:75` tmp+os.replace 模式（D-04..D-06）。

### 暴露面硬化清单（logs/errors/params/git）
- **D-18:** P2 遗留 WR-02/WR-03 纳入本阶段：writer-hammer 测试空转缺陷 + dot-segment 契约钉（TestClient 200 vs 实况 uvicorn 404）修正。
- **D-19:** 机器可读错误码 + 双 404 文案归一纳入：统一 `{"detail": ...}` 风格（D-04 基调），4xx/5xx 响应带机器可读错误码字段，404 文案单一定稿。
- **D-20:** openapi schema 同步更新 + README「已知限制」段（SC5 硬要求：single-flight 范围、剩余并发入口）。
- **D-21:** 日志硬化：uvicorn 访问日志保持默认不记 header；新增审计规则——job 子进程输出日志禁止包含 X-API-Key 值（测试覆盖，SC3）。
- **D-22:** 承接自 P3：WR-01 启动级修复（D-12）——非回环绑定 env 强制 token + 控制台警告，fail-closed boot check 有测试覆盖（SC2）。

### 分级政策文档化（SEC-02，用户已 sign-off）
- **D-23:** 权威落点：PROJECT.md security 条款内嵌数据分级表（数据类别→端点→保护级别），README 同步引用。
- **D-24:** PROJECT.md 措辞修订（用户已确认）：现「数据分级鉴权」句扩展为两级分级表——公开级（/health、/health/ready、GET /v1/state/* 行情温度）｜机密级（GET /v1/private/* 持仓账本候选 + 全部 POST /v1/actions/* + GET /v1/jobs/*）一律 X-API-Key；保留定稿标注「改动需用户确认」。
- **D-25:** 版本注记：表内注明「2026-09-02 用户确认 + Phase 4 定稿 2026-09-04」，链接隐私红线（2026-08-31）。

### 触发 date 参数面（D-09 扩展，SC4）
- **D-26:** pipeline 和 morning-check 接受可选 `date` 参数（YYYY-MM-DD / YYYYMMDD 白名单）；backtest-weights、health-check 零参数不变（重搜无历史概念、体检只看当下）。
- **D-27:** 非法格式 → 422 + detail 说明白名单格式。
- **D-28:** 传参方式：附加到固定命令 arg-list 末尾（`run_pipeline.py --fast --date=YYYY-MM-DD` / `morning_check.py --quick --date=...`），仍无 shell——SC4「reach scripts as argument lists」字面。

### Claude's Discretion
- /v1/private/ 路由模块结构与命名（参照 api/state.py 纯函数风格）；白名单映射表形态。
- 错误码字段命名与 4xx/5xx 错误码表（机器可读，不泄露路径）。
- date 参数校验函数位置（参数校验是 FastAPI 依赖还是路由内）。
- 分级审计（SC2 route-by-route audit）的落地形态（测试断言式 or 文档表 + 测试双保险）。
- PROJECT.md 分级表的具体表格排版。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `api/state.py` — Phase 2 防御式读层（validate-then-serve + 短重试 + last-good stale 缓存）；/v1/private/ 直接复用同一读层，仅映射目标不同（logs/portfolio.json、logs/trading_journal.json、logs/candidates_*.json）。
- `api/auth.py` — Phase 3 鉴权依赖（X-API-Key constant-time 比较，401/403 分工）；机密级路由挂同一依赖。
- `api/main.py` — 路由挂载点；分级 = 依赖挂载差异（/v1/private/* 挂 auth，/v1/state/* 不挂）。
- `scripts/daily/zt_pool.py:72-78` — tmp+os.replace 原子写参照模式（D-04..D-06 改造模板）。
- `tests/conftest.py` — 零网络 autouse fixture；Phase 4 测试同轨。
- `api/jobs.py` / `api/actions.py` — Phase 3 触发链路；date 参数在此追加 arg-list。

### Established Patterns
- 最小 diff 惯例：api/main.py 每次仅加 import + include_router 两行式变更（Phase 1/2/3 惯例，继续遵守）。
- raw 透传定稿（D-01）：永不重序列化，字节级原样 + 新鲜度头。
- 数据引用纪律：API 不改脚本逻辑、不解析脚本输出做决策。
- 定稿机制：分级政策、错误文案等定稿项改动需用户确认。

### Integration Points
- `run_api.bat` / Task Scheduler 自启：WR-01 修复改动启动路径（env 强制 token），SEC-03 检查顺序保持 diff 可审计。
- `logs/` 已 gitignore；data/api_token.txt 同 commit gitignore（SC5 扫描对象）。
- sync_cloud 白名单：锁文件/job registry/api_token 均不得进入（SC5 扫描对象）。
- Phase 5 衔接：OPS-03 日志轮转 + /health/details 不在此阶段做；错误码表供 Phase 5 复用。
</code_context>

<specifics>
## Specific Ideas

- SC5 要求 README 文档化已知限制：single-flight 范围（同 kind 409）、剩余并发入口（Mac crontab 无锁、手动 CLI/GUI——GUI 已弃用仅 CLI）。
- 写侧原子化仅两个函数，不做 logs/ 全量扫描（D-05）。
</specifics>

<deferred>
## Deferred Ideas

- job 取消（taskkill 树杀）与孤儿任务收养打磨 — REQUIREMENTS.md v2（ACT-04/ACT-05），仅当真实出现失控运行时。
- 日志轮转 + 鉴权版 /health/details — Phase 5（OPS-03）。
- ETag/304、按客户端限流、管线 digest 聚合接口 — v2（OPS-04/05/06）。
- 15:30 定时任务存废确认 — Phase 5 ops polish（STATE.md [P3→P5]）。
</deferred>
