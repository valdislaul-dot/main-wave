# Win 端 Claude 自动设置指南

> 这是 Mac 端 Claude 留给 Win 端 Claude 的信息。请按顺序执行。

## 当前项目状态

- 模型版本：v4.0（评分V3.2 + 卖点V4.0）
- 回测结果：保持最新回测为准
- Mac 端最后更新：2026-07-27

## 你需要做的事（按顺序）

### 1. 初始化 Git

```bash
cd C:\Users\Davis\Desktop\主升浪
git init
git remote add origin https://github.com/valdislaul-dot/gogo.git
git pull origin main
```

### 2. 读取上下文

读这两个文件了解全部上下文：

- `CLAUDE.md` — 模型规则速查
- `CONTEXT.md` — 完整上下文（持仓、回测、操作流程、关键论证）

### 3. 设置 Git 用户名

```bash
git config user.name "Davis"
git config user.email "davis@win.com"
```

### 4. 验证

```bash
git log --oneline -5
```

看到最近提交记录说明同步成功。

---

## 日常同步规则

### 每次开始前
```bash
git pull
```
然后告诉 Claude：「读取 CLAUDE.md 和 CONTEXT.md」

### 每次结束后
告诉 Claude：「提交并推送」，我会按下面格式写 commit：

```
[日期 周几 · Win] 简短标题

更新内容:
- xxx

作用:
- xxx
```

### 如果有冲突
告诉 Claude：「git pull 有冲突，帮我解决」，提供冲突内容。

---

## 注意事项
- 数据文件（kline_data、logs、results）不会上传到 GitHub
- 只同步代码、配置和上下文文件
- Win 端路径 `C:\Users\Davis\Desktop\主升浪` 已在所有脚本中自动检测
