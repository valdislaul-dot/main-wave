# Retrospective

## Milestone: v1 — gogo API 服务

**Shipped:** 2026-09-05
**Phases:** 5 | **Plans:** 18 | **Tasks:** 40

### What Was Built
gogo 的批处理管线变成了常驻可查询 HTTP 服务：/health 探活 + fail-closed 启动（P1）→ raw 透传状态读取 + 防御读层（P2）→ 触发运行器 + 持久 job registry + 单飞锁 + X-API-Key（P3）→ 数据分级 /v1/private token 门控 + 错误信封 + 暴露面硬化（P4）→ /health/details + 日志有界 + 真机 gate（P5）。最终 193 passed + 1 env-conditional skip，6/6 E2E 流 wired，14/14 requirements satisfied。

### What Worked
- **真机 gate 纪律（03-04/04-07/05-04 三连）**：每个阶段以真机 live 矩阵 + 人类终审收尾，三次 gate 各自 live 实测推翻规划假设（`python -m` 双身份、cmd >> deny-share 句柄），adapt-and-record 而非纸上谈兵。
- **机器验证事实优先于规划假设**：pattern-mapper 的 live 实验（WinError 32、Errno 13）提前暴露两个不可行假设，planner 在计划阶段就拿到硬约束。
- **checker 的算术级验证**：cap-20 测试边界错误（23 vs 20）在计划阶段被算死，避免了执行期 stall。
- **代码 review + fix 循环**：两阶段共 11 个 warning 全部闭环（7+4），含 2 个实盘语义防御（record_sell 错配拒绝、拒绝路径 exit 1）。

### What Was Inefficient
- **harness worktree fork base（#2649）**：Wave 1 两个 executor 全部 exit 42（origin/HEAD 落后 93 commits），浪费两轮 dispatch；降级 sequential 后全程顺序执行。修复需要 push 同步 origin/HEAD（受上传纪律约束未做）。
- **decision coverage gate 格式往返**：CONTEXT.md 决策未编号导致 gate 解析失败，重写 D-NN 编号 + 回填计划引用，往返一次。
- **ROADMAP 双写**：planner 改 wave 分组后 ROADMAP wave 列表漂移，靠 checker 二轮发现。

### Patterns Established
- **D-NN 决策编号链**（D-01..D-37 跨 5 阶段连续编号），CONTEXT.md 决策块必须 `- **D-NN:**` 格式。
- **真机 live gate 模板**（03-04 定型）：重启 → live 矩阵 → 假设行验证 → 人类终审 15 行 ACCEPT/DELTA。
- **错误信封冻结码表**：新端点零新错误文本，raise site 永不编辑。
- **boot 顺序 diff 可审计**：api/main.py 每阶段最小 diff（import + include_router + 单一插入块）。

### Key Lessons
- 规划期假设标注 [ASSUMED] 并按 live gate 逐行裁决，是「假设→实测→适应」闭环的核心——三个假设被 live 推翻但零返工。
- sequential 执行虽然慢于并行，但在单用户 Windows 机器上可预测性优先。
- shared-ID gate（requirements.ready-ids）正确防止了提前翻需求——让最后一个计划执行者翻。

### Cost Observations
- Model mix: 计划/修订 opus，执行/审查/验证 sonnet，检查 haiku（checker 用 haiku 做了 3 轮高质量算术验证，成本极低）
- 单会话全程自动化：discuss → plan → execute → verify → audit → archive
- Notable: checker 的 deterministic probes（verify-command-paths / failing-directions）把机械检查前置到 LLM 之前，发现 0 假阳

## Cross-Milestone Trends

（v1 为第一个里程碑，趋势从 v2 起积累。）
