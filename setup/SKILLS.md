# 主升浪项目所需 Skills

> 在 Claude Code 中使用本项目的 Win/Mac 端都需要安装这些 skills。

## 1. a-stock-data — A股全栈数据工具包

**用途**：拉取行情/K线/涨停池/龙虎榜/财务数据，替代 akshare。直连东财/通达信/腾讯，不封 IP。

**安装**：
```bash
mkdir -p ~/.claude/skills/a-stock-data
curl -fsSL https://raw.githubusercontent.com/simonlin1212/a-stock-data/main/SKILL.md -o ~/.claude/skills/a-stock-data/SKILL.md
pip install mootdx requests pandas stockstats
```

**本项目使用场景**：
- `screen_candidates.py` 拉取涨停池（东财 push2ex）
- K线数据补充
- 竞价分析辅助

**来源**：https://github.com/simonlin1212/a-stock-data

---

## 2. planning-with-files — 持久化任务规划

**用途**：跨 /clear 保持任务计划，context 压缩后自动恢复。

**安装**：
```bash
mkdir -p ~/.claude/skills/planning-with-files
git clone --depth 1 https://github.com/OthmanAdi/planning-with-files.git /tmp/pwf
cp /tmp/pwf/skills/planning-with-files/skill.md ~/.claude/skills/planning-with-files/SKILL.md
```

**本项目使用场景**：
- 新任务规划（非主升浪项目使用）
- 主升浪本身用 CLAUDE.md + CONTEXT.md 已够用

**来源**：https://github.com/OthmanAdi/planning-with-files

---

## 本项目 Python 依赖

```bash
pip install mootdx requests pandas stockstats openpyxl
```

## Win 端一键安装

Win 端 Claude 读取此文件后，运行：
```bash
mkdir -p ~/.claude/skills/a-stock-data
curl -fsSL https://raw.githubusercontent.com/simonlin1212/a-stock-data/main/SKILL.md -o ~/.claude/skills/a-stock-data/SKILL.md
mkdir -p ~/.claude/skills/planning-with-files
git clone --depth 1 https://github.com/OthmanAdi/planning-with-files.git /tmp/pwf
cp /tmp/pwf/skills/planning-with-files/skill.md ~/.claude/skills/planning-with-files/SKILL.md
pip install mootdx requests pandas stockstats openpyxl
```
