# Phase 1: Service Skeleton + /health Liveness - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-02
**Phase:** 1-Service Skeleton + /health Liveness
**Areas discussed:** API 代码落位, Token 供给机制, 自启触发方式

---

## API 代码落位

| Option | Description | Selected |
|--------|-------------|----------|
| 顶层 api/ 独立包 | api/main.py + api/routes/ 等包结构。常驻服务与日更批处理脚本彻底分离，pytest 导入天然可用，Phase 2-5 增长有空间；config.py 路径常量直接用。 | ✓ |
| scripts/api/ 包 | 与现有脚本同父目录；但与 scripts/ 根目录 70 只研究脚本混杂，且 scripts/ 下从未有包结构先例。 | |
| scripts/daily/ 平铺 | 完全沿袭现有惯例，但常驻服务混入交易日更流水线目录，pytest 导入需 sys.path 技巧。 | |

**User's choice:** 顶层 api/ 独立包 (Recommended)
**Notes:** 用户确认后直接进入下一区域，无补充说明。

---

## Token 供给机制

| Option | Description | Selected |
|--------|-------------|----------|
| 首次启动自动生成 | secrets 生成随机 token 写入 data/api_token.txt，单用户工具零配置。 | ✓ |
| 手动预置文件 | 用户自己创建，代码最简单，但多一步人工操作，无随机性保证。 | |
| 仅环境变量 | 最干净，但计划任务要配环境变量，双端运维摩擦大。 | |

**User's choice:** 首次启动自动生成 (Recommended)

**Follow-up Q1 — 环境变量覆盖：**

| Option | Description | Selected |
|--------|-------------|----------|
| 支持环境变量覆盖 | GOGO_API_TOKEN 优先、文件兜底，与 tushare 惯例（kline_source.py:26）一致。 | ✓ |
| 仅文件单一来源 | 单一数据源最简单，但与现有惯例不一致。 | |

**User's choice:** 支持环境变量覆盖 (Recommended)

**Follow-up Q2 — 生成后如何告知用户：**

| Option | Description | Selected |
|--------|-------------|----------|
| 只提示文件路径 | 不打印值，与 Phase 4 SC3 日志审计零冲突；重置=删除文件重启。 | ✓ |
| 控制台打印值一次 | 前台运行直观，但计划任务重定向时值进启动日志，与 Phase 4 审计冲突。 | |
| 打印值+notice 文件 | 多一个文件多一处泄露面。 | |

**User's choice:** 只提示文件路径 (Recommended)
**Notes:** 硬性要求（Claude 提出，未列为选项）：.gitignore 加 data/api_token.txt 必须与生成代码同一提交——仓库疑似公开（匿名访问 200）+ sync_cloud 每日自动 commit。

---

## 自启触发方式

| Option | Description | Selected |
|--------|-------------|----------|
| 沿用现有惯例 AtStartup | AtStartup+5min 随机延迟、当前用户 Interactive、StartWhenAvailable、Restart 3×10min、IgnoreNew，与现有管线任务一致，无新增权限面。 | ✓ |
| 开机即启 SYSTEM 主体 | 无人登录也跑，真 24/7；但 SYSTEM 无用户环境、扩大权限面。 | |
| 登录时启动 Logon | 比 AtStartup 少一次空窗，但用户登录前起不来，多一种运维形态。 | |

**User's choice:** 沿用现有惯例 AtStartup (Recommended)

**Follow-up — 默认端口：**

| Option | Description | Selected |
|--------|-------------|----------|
| 8000 默认+环境变量可改 | uvicorn 默认，与 Streamlit 8501 无冲突，LB 探活指向 127.0.0.1:8000/health。 | ✓ |
| 9000 | 与 8000 错开，但无现成惯例支撑。 | |
| 其他指定端口 | 用户基础设施已规划端口（未选）。 | |

**User's choice:** 8000 默认+环境变量可改 (Recommended)

---

## Claude's Discretion

用户未表态、由 Claude 决定并写入 CONTEXT.md 的事项：
- requirements.txt 增加 fastapi/uvicorn/pytest/httpx（Mac 端可跑）
- run_api.bat 用 %~dp0 相对定位（不复制 auto_start.bat 硬编码旧路径 bug）
- uvicorn 日志落 logs/api/（已 gitignored）；单进程 programmatic 启动
- 测试放顶层 tests/ + 网络封锁 fixture；token 生成需测试安全（不碰真实 data/api_token.txt）
- token 文件格式、非回环无 token 的报错文案、8000 端口冲突行为
- Mac 端自启（launchd plist）未选讨论 → 按 ROADMAP 默认留 Phase 5

## Deferred Ideas

- Mac launchd plist — Phase 5 Win/Mac parity
- 本轮讨论未产生新的 roadmap backlog 项；REQUIREMENTS.md v2 列表为既有延期项
