# Phase 2: Read-Only State Endpoints + Defensive Read Layer - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

## Phase Boundary

外部消费方经 HTTP 读取 gogo 当前市场/竞价/涨停池状态——原始 JSON 文件体 + 新鲜度头,且管线写入过程中永不读到撕裂/半写文件。

**In scope:** HLT-02 (GET /health/ready 就绪——stat 存在性/可读性,仅不可读 503,不看数据新旧), STA-01 (GET /v1/state/{name} 透传 market_state/auction_state/zt_pool_state + X-Data-Mtime/X-Data-Age-S 新鲜度头), STA-03 (防御性读层——开→读→关、JSONDecodeError 短重试、末次成功缓存回退带 stale 标记)。

**Not this phase:** 持仓/账本/候选读取接口 (STA-02, Phase 4 数据分级), 操作触发 (ACT-*, Phase 3), token 请求鉴权 (SEC-01, Phase 3), 数据分级策略落地 (SEC-02, Phase 4), 日志轮转/health/details (OPS-03, Phase 5), ETag/304 (OPS-04 v2)。

**Success criteria** (from ROADMAP.md, must all be TRUE):
1. GET /v1/state/market_state (或 auction_state/zt_pool_state) 返回管线写入的原始 JSON 文件体,附 X-Data-Mtime 与 X-Data-Age-S 头(源于文件真实 mtime)。
2. 管线写入状态文件期间,反复 GET 所有服务文件返回 0 × 5xx——半写 JSON 永不送达;持续解码失败时消费方收到末次成功载荷并显式标 stale,永不静默成功或裸 500。
3. GET /health/ready 在所有服务文件存在且可读时 200;仅缺失/不可读时 503。数据陈旧(夜间/周末/假期)永不 503。
4. 代码审计(grep)证明任何 GET 处理器无外部网络调用——读层是纯本地文件读,开→读→关。

## Implementation Decisions

### 透传契约 (Decision A — 用户已签名)
- **D-01:** GET /v1/state/{name} 响应体 = 管线写入的原始 JSON 文件体,逐字节透传,不加工、不封装。新鲜度通过响应头表达:X-Data-Mtime(文件 mtime,Unix epoch 秒,整数)与 X-Data-Age-S(now − mtime,整数秒)。— **Reversibility:** one-way — 一旦外部消费方按 raw body 契约接入,改为 JSON 信封 {meta,data} 会破坏全部既有消费方(ROADMAP SC1 亦字面要求 "raw JSON file body exactly as the pipeline wrote it")。
- **D-02:** 成功响应 Content-Type: application/json;透传时响应体不做任何重格式化(保留原字节,含管线写出的缩进/键序)。

### 服务范围与错误码 (白名单)
- **D-03:** /v1/state/{name} 仅接受固定三名的显式映射:`market_state` → `data/market_state.json`、`auction_state` → `data/auction_state.json`、`zt_pool_state` → `data/zt_pool_state.json`。未知名一律 404。不做 DATA_DIR 下任意文件名的动态解析——无路径穿越面,Phase 4 分级前持仓/账本/候选天然不可达(SEC-02 精神先行)。— **Reversibility:** costly — 新增服务文件需加映射+测试,但这是有意的窄入口而非缺陷;未来 STA-02/新状态名按 Phase 4 分级政策在同一映射表扩展。
- **D-04:** 错误码分工:未知名 404(客户端错误);已知名但文件缺失/不可读 503(服务端问题,与 /health/ready 同口径)。持续解码失败不回 5xx,而是回退末次成功缓存(STA-03 字面),见 D-05。错误体用 FastAPI 惯例的最小 JSON `{"detail": "..."}`,不含文件路径。

### 防御性读层 (STA-03)
- **D-05:** 读层协议:open → read → close(每次请求完整打开关闭,不持长句柄);JSONDecodeError 短重试(读新的文件快照);持续失败回退进程内末次成功缓存,响应头标 `X-Data-Stale: true`(体仍是合法 JSON = 末次成功载荷,消费方可正常解析)。stale 标记只在回退路径出现,正常路径不发送该头。— **Reversibility:** reversible — 纯内部读策略,消费方契约仅多一个可选响应头。

### Claude's Discretion
- /health/ready (HLT-02/Decision E) 按需求字面:3 个白名单文件全部存在且可读 → 200;任一缺失/不可读 → 503;数据新旧不参与判断(夜间/周末/假期永不 503)。就绪检查体保持最小 JSON(与 Phase 1 /health 同风格)。
- stale 兜底不做主动年龄阈值(用户未选该区):仅解码失败触发回退;消费方用 X-Data-Age-S 自行判新旧。
- 末次成功缓存的实现位置(进程内模块级缓存/每名一槽)与短重试次数(2-3 次)由研究/规划按 STA-03 字面选定。
- 读层函数放 api/ 包内新模块(如 api/state.py),沿 D-02 路径纪律从 scripts/daily/config.py 导入路径常量;禁止在 GET 处理器中出现任何 requests/urllib 调用(SC4 grep 审计)。

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning docs
- `.planning/ROADMAP.md` — Phase 2 goal、4 条成功标准(0×5xx、stale 标记、ready 口径、grep 审计)、Research skip 说明(Decision A/E 已在需求中钉死)
- `.planning/REQUIREMENTS.md` — HLT-02/STA-01/STA-03 逐字契约;STA-02 属 Phase 4 的映射;Out of Scope 表(PUT/PATCH 改写、CORS、GET 实时抓取)
- `.planning/PROJECT.md` — Key Decisions(raw passthrough 推荐项、数据分级鉴权);Constraints(reuse 只读、不引入第二数据源)
- `.planning/phases/01-service-skeleton-health-liveness/01-CONTEXT.md` — Phase 1 锁定决策 D-01..D-10(api/ 包、config.py 导入、端口 8000、/health 纯度)

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md` — 状态文件分类(可变单点 state 原子写 tmp+os.replace vs 每日快照)、反模式(路径样板重复、try/except 吞错)、错误处理(原子写、守卫模式)
- `.planning/codebase/INTEGRATIONS.md` — 云面板消费方 gui_cloud.py 读 market_state/auction_state/zt_pool_state 快照(本阶段接口的天然消费场景)

### Existing code
- `scripts/daily/config.py` — PROJECT_ROOT/DATA_DIR/LOG_DIR 唯一路径来源(api/ 必须从此导入)
- `api/main.py` — Phase 1 路由挂载点,新路由在此注册;main() 启动顺序勿破坏 SEC-03 检查
- `api/boot.py` — 纯函数模式(显式参数、零 print)可作读层模块的风格参照
- `scripts/daily/zt_pool.py` §72-75 — 原子写实现(tmp + os.replace),读层必须防御的写入模式
- `tests/conftest.py` — 零网络 autouse fixture 延续;Phase 2 测试同轨(TestClient + tmp_path 假状态文件)

## Existing Code Insights

### Reusable Assets
- `api/main.py` 的 FastAPI app 与 `if __name__ == "__main__"` 守卫:新路由直接 `app.get("/v1/state/{name}")` 挂载。
- Phase 1 的 boot 纯函数模块模式(`api/boot.py`):读层核心逻辑抽成可测试纯函数(文件路径、缓存、mtime 显式传入)。
- `tests/` 套件基础设施(pytest.ini pythonpath=.,conftest 网络封锁):Phase 2 测试直接用,假状态文件走 tmp_path。

### Established Patterns
- 状态文件原子写(tmp + os.replace):半写窗口极短,但读层仍按 STA-03 防御(JSONDecodeError 重试+缓存回退)。
- `data/market_state.json`/`auction_state.json`/`zt_pool_state.json` 是可变单点状态,盘后/竞价时段被管线重写——读层必须容忍 mtime 连续变化。
- 数据引用纪律:API 透传文件体,绝不二次加工或推测覆盖数据。
- 单进程纪律:读层缓存是进程内的;服务重启后缓存为空,首次请求冷启动直读文件(文件此时必然存在或 503)。

### Integration Points
- 消费方现状:`gui_cloud.py`(云端只读面板)直接读同一批状态文件——本接口是它的 HTTP 化等价物;新鲜度头为云面板提供"数据新旧"判断能力。
- Phase 4 数据分级:固定白名单(D-03)是分级边界的第一道墙;STA-02(持仓/账本/候选)加入时在映射表内扩展并挂 token。
- ROADMAP 成功标准 4 的 grep 审计:计划必须含一个可运行的审计 verify 命令(如 `grep -n "requests\.\|urllib" api/state.py` 为空)证明读层零网络。

## Specific Ideas

无额外特定引用——透传形状与白名单已由用户明确选定,其余按需求字面与 Claude 裁量。

## Deferred Ideas

- None — discussion stayed within phase scope (todo match count: 0)。未选的两区(stale 年龄阈值、ready 检查集细化)按 ROADMAP/需求字面落入 Claude's Discretion。

---

*Phase: 2-Read-Only State Endpoints + Defensive Read Layer*
*Context gathered: 2026-09-03*
