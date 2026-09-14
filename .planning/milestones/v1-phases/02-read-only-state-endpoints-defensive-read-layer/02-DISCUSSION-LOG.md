# Phase 2: Read-Only State Endpoints + Defensive Read Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-03
**Phase:** 2-read-only-state-endpoints-defensive-read-layer
**Areas discussed:** 透传形状 (Decision A), 可服务文件白名单

---

## 透传形状 (Decision A)

| Option | Description | Selected |
|--------|-------------|----------|
| Raw + 新鲜度头 (推荐) | 响应体 = 管线写的原始 JSON 字节;新鲜度通过 X-Data-Mtime(文件 mtime 秒)与 X-Data-Age-S(now-mtime)两个头表达。与既有 JSON schema 零适配。ROADMAP 推荐项。 | ✓ |
| JSON 信封 {meta,data} | 自描述、可扩展,但破坏 "verbatim 文件体" 契约,违反 ROADMAP SC1 字面成功标准。 | |
| You decide | 由研究/规划阶段选定并记录为裁量项。 | |

**User's choice:** Raw + 新鲜度头 (推荐) — Decision A 签名。
**Notes:** 跟进问题确认 X-Data-Mtime / X-Data-Age-S 格式为 Unix epoch 秒(整数),与现有系统 Unix 秒风格一致。

---

## 可服务文件白名单

| Option | Description | Selected |
|--------|-------------|----------|
| 固定 3 名映射 (推荐) | name 只接受 market_state / auction_state / zt_pool_state 三个显式映射。未知名 404,天然无路径穿越面;Phase 4 分级边界清晰。 | ✓ |
| DATA_DIR 内任意 JSON | 扩展零代码但暴露面大,Phase 4 分级前可能漏出持仓/账本。 | |
| You decide | 由计划阶段选定并记录为裁量项。 | |

**User's choice:** 固定 3 名映射 (推荐)。
**Notes:** 跟进问题确认错误码分工:未知名 404(客户端错误)、已知名但缺失/不可读 503(与 /health/ready 同口径)。持续解码失败回退末次成功缓存 + stale 头,不回 5xx。

---

## Claude's Discretion

- /health/ready (HLT-02/Decision E) 按需求字面:3 个白名单文件全部存在且可读 → 200,任一缺失/不可读 → 503,数据新旧不参与判断。
- stale 兜底不做主动年龄阈值(用户未选该区):仅解码失败触发回退。
- 末次成功缓存实现位置、短重试次数、读层模块名(api/state.py)由研究/规划选定。

## Deferred Ideas

None — discussion stayed within phase scope。
