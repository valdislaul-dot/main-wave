# 主升浪 V4.0 — 完整使用说明

---

## 一、环境安装

### Windows / Mac / Linux
```bash
# Python 3.10+
pip install -r requirements.txt
```

### iOS / 出门在外

**Streamlit Cloud 部署（免费，推荐）:**

```bash
# 1. 把项目 push 到 GitHub
git init && git add . && git commit -m "v4.0"
git remote add origin https://github.com/你的用户名/main-wave.git
git push -u origin main

# 2. 打开 share.streamlit.io
#    → New app → 选仓库 → Main file: scripts/daily/gui_dashboard.py
#    → Deploy!

# 3. 获得链接 https://xxx.streamlit.app
#    iPhone/Safari 直接打开，添加到主屏幕=原生App体验
```

首次启动会自动下载K线（~10分钟），之后秒开。

---

## 二、首次初始化

```bash
cd scripts/daily

# 1. 下载K线（一次性，~15分钟，腾讯fqkline前复权）
python fetch_backtest_klines.py

# 2. 运行流水线
python run_pipeline.py
```

---

## 三、每日操作

```
15:00 盘后 → python run_pipeline.py          （更新数据+选股）
09:25 竞价 → streamlit run gui_dashboard.py   （看候选+决策）
             浏览器打开 http://localhost:8501
09:30 开盘 → 执行买卖
```

### CLI 交易记录
```bash
python run_pipeline.py --buy  标的名称 代码 买入价 股数
python run_pipeline.py --sell 标的名称 代码 卖出价
python run_pipeline.py --status
```

---

## 四、GUI 面板

```bash
streamlit run scripts/daily/gui_dashboard.py
```

| 区域 | 说明 |
|------|------|
| 持仓概览 | 总资产、现金、持仓标的、胜率 |
| 涨停池 | 全部标的 V3评分排序 + 风控过滤 |
| 评分拆解 | 量比/Gap/一字/连板/封板/炸板/板块 |
| 侧边栏 | 一键运行流水线 |

---

## 五、Mac 专属配置

Mac端自动检测平台（config.py已处理路径差异）。

首次运行前给脚本执行权限：
```bash
chmod +x scripts/daily/*.py
```

定时任务（可选）：
```bash
# 每个交易日下午3点自动运行
crontab -e
0 15 * * 1-5 cd /path/to/main-wave && python scripts/daily/run_pipeline.py
```

---

## 六、V4.0 双引擎模型（评分V3 + A卖点体系）

| 因子 | 档数 | 说明 |
|------|------|------|
| 量比 | 11档 | 连板≥2用5日均量 |
| 封板时间 | 11档 | 0-5min+14, 60min+-10 |
| 板块共振 | 3档 | ≥5只+12 |
| 连板 | 3档 | 首板-4, 2-3板+10, 4板++15 |
| 炸板 | 动态 | 早回封-2×n, 晚回封-15×n |
| Gap | 9档 | ≥10%+22, 1-3%-1 |
| 一字板 | 2档 | 真一字+20, T字+10 |

### 风控
300/301/688排除 | 真一字跳过 | 4板+一字跳过 | 评分<10不买 | -10%止损

### 三年回测
≥10门槛: **+2,734%** (200k→568万)

---

## 七、常见问题

**Q: 想在iPhone上看候选？**
A: Mac上跑 `streamlit run gui_dashboard.py`，iPhone浏览器打开 `http://Mac的IP:8501`

**Q: 出门在外怎么看？**
A: 部署到 Streamlit Cloud (免费)，获得 `xxx.streamlit.app` 公开链接

**Q: 涨停池只有几只？**
A: 运行 `python run_pipeline.py` 自动拉取当天数据

**Q: 评分全是0？**
A: 确认已运行 `python fetch_backtest_klines.py` 下载K线数据
