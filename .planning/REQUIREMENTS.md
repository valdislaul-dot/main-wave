# Requirements: gogo API 服务 (main-wave API)

**Defined:** 2026-09-02
**Core Value:** 外部系统通过一个稳定的 HTTP API 就能拿到 gogo 的实时状态（探活/持仓/温度/市场状态）并触发核心操作（管线/竞价/回测），且不干扰现有管线的运行

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### 健康检查 (HLT)

- [ ] **HLT-01**: GET /health 探活——纯内存返回 `{"status":"ok","uptime_seconds":N}`，永远 200，不受鉴权拦截，数据过期绝不 503
- [ ] **HLT-02**: GET /health/ready 就绪——stat 状态文件存在性/可读性，仅不可读时 503，不看数据新旧

### 只读状态 (STA)

- [ ] **STA-01**: GET /v1/state/{name} 行情/温度透传（market_state/auction_state/zt_pool_state），原始文件体 + X-Data-Mtime/X-Data-Age-S 新鲜度头
- [ ] **STA-02**: 持仓/账本/候选读取接口（数据分级：token 保护）
- [ ] **STA-03**: 防御性读层——开→读→关、JSONDecodeError 短重试、末次成功缓存回退带 stale 标记（半写文件防护）

### 触发接口 (ACT)

- [ ] **ACT-01**: POST /v1/actions/{kind} 四种触发：管线(pipeline)/竞价(morning-check)/回测(backtest-weights)/体检(health-check)，只启动现有脚本，不改其逻辑
- [ ] **ACT-02**: 202+job_id 异步契约 + 持久化 job registry（logs/api/jobs/，重启可恢复）
- [ ] **ACT-03**: 单飞锁防并发（进程内+锁文件+PID 探活，重叠返回 409）

### 安全 (SEC)

- [ ] **SEC-01**: X-API-Key 鉴权（constant-time 比较，header 传递，永不上日志）
- [ ] **SEC-02**: 数据分级鉴权——行情/温度放开，持仓/账本/候选/触发一律 token
- [ ] **SEC-03**: 默认绑 127.0.0.1，非回环无 token 拒绝启动（fail-closed）

### 运维 (OPS)

- [ ] **OPS-01**: Windows 任务计划程序开机自启（run_api.bat，沿用 install_scheduled_task.ps1 惯例）
- [ ] **OPS-02**: pytest+TestClient 种子测试（仓库首套自动化测试）
- [ ] **OPS-03**: 日志轮转 + 鉴权版 GET /health/details

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### 触发增强 (ACT)

- **ACT-04**: job 取消（taskkill 树杀）——仅当真实出现失控运行时
- **ACT-05**: 孤儿任务收养打磨（启动时 running+死 PID → orphaned 的清理策略）

### 性能与运维 (OPS)

- **OPS-04**: ETag/304 条件请求——仅当轮询量证明需要
- **OPS-05**: 按客户端限流——仅当出现 off-localhost 部署
- **OPS-06**: 管线 digest 聚合接口（data_health_check 8 项报告 + warning 字段）

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Celery/Redis/RQ 队列 | 单用户单飞系统，进程外队列是过度基础设施 |
| WebSocket 推送 | 无实时消费方，轮询足够 |
| Webhooks | 无外部系统订阅场景 |
| PUT/PATCH 状态改写接口 | 定稿机制：API 不做第二写入方，管线是唯一业务写入者 |
| JWT/OAuth/用户管理 | 单用户工具，API Key 足够 |
| 自动实盘下单 | 安全边界，另行明确授权才考虑 |
| CORS 中间件 | 无浏览器消费方；出现时用显式 origin 列表，绝不 `["*"]`+credentials |
| GET 实时抓数据刷新 | 数据源限流封禁风险 + 竞价 60s SLA 窗口污染 |
| Node/Express 实现 | 已定 FastAPI，gogo 全 Python 栈 |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| HLT-01 | Phase 1 | Pending |
| HLT-02 | Phase 2 | Pending |
| STA-01 | Phase 2 | Pending |
| STA-02 | Phase 4 | Pending |
| STA-03 | Phase 2 | Pending |
| ACT-01 | Phase 3 | Pending |
| ACT-02 | Phase 3 | Pending |
| ACT-03 | Phase 3 | Pending |
| SEC-01 | Phase 3 | Pending |
| SEC-02 | Phase 4 | Pending |
| SEC-03 | Phase 1 | Pending |
| OPS-01 | Phase 1 | Pending |
| OPS-02 | Phase 1 | Pending |
| OPS-03 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 14 total (14 IDs enumerated: HLT 2 + STA 3 + ACT 3 + SEC 3 + OPS 3; prior "15 total" count was an off-by-one in the coverage block — corrected 2026-09-02 during roadmap creation)
- Mapped to phases: 14
- Unmapped: 0

---
*Requirements defined: 2026-09-02*
*Last updated: 2026-09-02 after roadmap creation (traceability filled, coverage count corrected)*
