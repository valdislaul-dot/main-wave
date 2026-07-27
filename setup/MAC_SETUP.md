# Mac 端 Claude 自动设置指南

> 当前设备的 Claude 参考。

## 项目路径
```
/Users/semple/Desktop/主升浪
```

所有脚本已通过 `os.path.dirname(__file__)` 自动检测 BASE，无需修改。

## 日常操作

### 开始前
```bash
git pull
```
然后读取 `CLAUDE.md` 和 `CONTEXT.md`

### 结束后
告诉 Claude：「提交并推送」

## Git 配置

已设置：
- remote: `https://github.com/valdislaul-dot/gogo.git`
- user: `semple / semple@mac.com`

## 定时任务

- launchd: 每周一至五 9:26 自动运行 `morning_check.py`
- CronCreate: 会话级 9:26 竞价提醒
- 盘后: `python3 scripts/daily/run_pipeline.py`
