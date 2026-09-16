"""D-04..D-06 账本写侧原子化契约测试 (Plan 04-02)。

背景: Phase 4 把 logs/portfolio.json + logs/trading_journal.json 通过 token 门控
端点对外服务 (STA-02) —— 读侧防御 (Phase 2) 已在, 写侧必须先原子化才能上线
(D-06 上线前置)。半写 JSON 永不作为新鲜数据被读到 (D-04 基调)。

模板 oracle: scripts/daily/zt_pool.py save_state (L72-78) 的 tmp+os.replace 原子写
—— 同目录 .tmp 兄弟文件保证与目标同卷 (NTFS 原子替换前提); os.replace 只在
Windows 上对已存在目标有效 (os.rename 会失败, 禁用)。
失败语义: tmp 写完、replace 抛错 → 目标保持上一次已提交内容 —— 崩溃永不丢失
最后落盘的账本。成功路径零 .tmp 残留; 失败路径残留被容忍 (实现钉死, Test 4)。

数据隔离钉: PORTFOLIO_FILE/JOURNAL_FILE 是调用时读取的模块全局 (seam), fixture
把它们 monkeypatch 到 tmp_path —— 本套件零接触真实 logs/ 账本文件。

改造前现状: save_portfolio/save_journal 是直接 open('w') 截断写 —— 截断发生在
任何可模拟失败之前, 目标已被覆盖 —— Test 3/Test 4 红正是 D-04 针对的缺陷。
"""
import json
import os

import pytest

import scripts.daily.trading_journal as tj


def _serialize(obj):
    """与写者相同的序列化参考 (ensure_ascii=False + indent=2)。"""
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def _normalize(raw):
    """Windows 文本模式写入会把 '\\n' 翻译成 '\\r\\n' —— 归一化后与参考字节比对。"""
    return raw.replace(b"\r\n", b"\n")


@pytest.fixture
def ledger_files(tmp_path, monkeypatch):
    """模块全局 seam: PORTFOLIO_FILE/JOURNAL_FILE 指向 tmp_path (调用时读取)。"""
    pf = tmp_path / "portfolio.json"
    jr = tmp_path / "trading_journal.json"
    monkeypatch.setattr(tj, "PORTFOLIO_FILE", str(pf))
    monkeypatch.setattr(tj, "JOURNAL_FILE", str(jr))
    return pf, jr


def _force_replace_failure_once(monkeypatch):
    """os.replace 首次调用抛 OSError (模拟 tmp 写完后、替换瞬间崩溃), 之后放行。"""
    real_replace = os.replace
    state = {"calls": 0}

    def flaky_replace(src, dst):
        state["calls"] += 1
        if state["calls"] == 1:
            raise OSError("simulated replace failure (D-04..D-06)")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    return state


# ---------- Test 1: 原子成功形态 (valid JSON / ensure_ascii=False / indent=2 / 零 .tmp) ----------

def test_atomic_success_shape_no_tmp_residue(ledger_files):
    pf_path, jr_path = ledger_files
    pf = {"positions": [{"code": "003040", "name": "楚天龙"}], "cash": 1415.5}

    tj.save_portfolio(pf)

    assert pf_path.exists()
    raw = pf_path.read_bytes()
    assert "楚天龙".encode("utf-8") in raw  # 中文以字面量出现 = ensure_ascii=False
    assert _normalize(raw) == _serialize(pf)  # indent=2 归一化字节与参考完全一致
    assert json.loads(raw) == pf
    assert list(pf_path.parent.glob("*.tmp")) == []  # 成功路径零 .tmp 残留

    journal = [{"date": "2026-09-04 10:00:00", "action": "BUY",
                "name": "楚天龙", "code": "003040", "price": 15.38,
                "shares": 2900, "cash_after": 1415.5}]

    tj.save_journal(journal)

    raw_j = jr_path.read_bytes()
    assert "楚天龙".encode("utf-8") in raw_j
    assert _normalize(raw_j) == _serialize(journal)
    assert json.loads(raw_j) == journal
    assert list(jr_path.parent.glob("*.tmp")) == []


# ---------- Test 2: 往返不变 (load_portfolio/load_journal 读回 == 输入结构) ----------

def test_round_trip_unchanged_through_loaders(ledger_files):
    pf_path, jr_path = ledger_files
    pf = {
        "cash": 1415.5,
        "position": {"code": "003040", "name": "楚天龙", "buy_date": "2026-08-25",
                     "buy_price": 15.379, "shares": 2900},
        "positions": [{"code": "003040", "name": "楚天龙", "buy_date": "2026-08-25",
                       "buy_price": 15.379, "shares": 2900}],
        "total_trades": 18, "winning_trades": 11, "total_pnl": 60223.3,
    }
    journal = [{"date": "2026-09-04 09:31:00", "action": "BUY",
                "name": "楚天龙", "code": "003040", "price": 15.38,
                "shares": 2900, "cost": 44602.0, "cash_after": 1415.5}]

    tj.save_portfolio(pf)
    tj.save_journal(journal)

    assert tj.load_portfolio() == pf
    assert tj.load_journal() == journal


# ---------- Test 3: replace 失败 → 目标保持上一次已提交内容 (逐字节) ----------

def test_replace_failure_keeps_previous_committed_content(ledger_files, monkeypatch):
    pf_path, _ = ledger_files
    good = {"positions": [], "cash": 1000.0}
    pf_path.write_bytes(_serialize(good))  # 上一次已提交的好内容

    _force_replace_failure_once(monkeypatch)

    new_pf = {"positions": [{"code": "003040", "name": "楚天龙"}], "cash": 1415.5}
    with pytest.raises(OSError):
        tj.save_portfolio(new_pf)

    # 目标文件逐字节保持旧内容 —— 崩溃发生在 tmp 写完后、替换前, 最后落盘账本不丢
    assert pf_path.read_bytes() == _serialize(good)


# ---------- Test 4: 失败路径残留纪律 (实现钉死: 模板无清理 → .tmp 滞留新内容; 目标必为旧内容) ----------

def test_failure_path_residue_pinned_target_holds_old(ledger_files, monkeypatch):
    pf_path, _ = ledger_files
    good = {"positions": [], "cash": 1000.0}
    pf_path.write_bytes(_serialize(good))

    _force_replace_failure_once(monkeypatch)

    new_pf = {"positions": [{"code": "003040", "name": "楚天龙"}], "cash": 1415.5}
    with pytest.raises(OSError):
        tj.save_portfolio(new_pf)

    tmp_path = pf_path.with_name(pf_path.name + ".tmp")
    # 按 zt_pool 模板实现 (无 try/finally 清理): 失败后 .tmp 滞留且内容=新内容;
    # (若未来实现选择清理, 此处改为断言 .tmp 不存在 —— 两种情形目标都必须=旧内容)
    assert tmp_path.exists()
    assert _normalize(tmp_path.read_bytes()) == _serialize(new_pf)
    assert pf_path.read_bytes() == _serialize(good)


# ---------- WR-02 (04 修复): record_sell 匹配语义 —— code 身份优先, name/code 错配拒绝 ----------

def _two_position_pf():
    """两只不同持仓 (positions 列表 + 兼容字段), record_sell 写路径字段齐备。"""
    return {
        'cash': 10000.0,
        'total_trades': 0,
        'winning_trades': 0,
        'total_pnl': 0.0,
        'position': {'name': '楚天龙', 'code': '003040', 'buy_date': '2026-09-01',
                     'buy_price': 15.0, 'shares': 100},
        'positions': [
            {'name': '楚天龙', 'code': '003040', 'buy_date': '2026-09-01',
             'buy_price': 15.0, 'shares': 100},
            {'name': '华天酒店', 'code': '000428', 'buy_date': '2026-09-02',
             'buy_price': 4.5, 'shares': 100},
        ],
    }


def test_record_sell_mismatch_name_code_refused_no_double_sell(ledger_files, capsys):
    """WR-02: A 的名字 + B 的代码 (手滑) -> 拒绝卖出; 两只持仓原样, 日志零 SELL。

    原 name-OR-code 并集在此输入下把 A/B 一并移除并记双卖 (WR-02 缺陷)。
    """
    pf = _two_position_pf()
    tj.save_portfolio(pf)
    tj.save_journal([])

    result = tj.record_sell('楚天龙', '000428', 5.0)  # 楚天龙名 + 华天酒店码

    assert 'WARNING' in capsys.readouterr().out
    assert result is None  # WR-07: 拒绝返回 None (run_pipeline --sell 映射为非零退出)
    assert tj.load_portfolio() == pf  # 拒绝 = 零改动 (文件内容不变)
    assert tj.load_journal() == []


def test_record_sell_correct_pair_sells_only_that_stock(ledger_files):
    """WR-02: 名码一致 -> 只卖该股; 他股保留 (2026-09-17: cash 口径已停用)。"""
    pf = _two_position_pf()
    tj.save_portfolio(pf)
    tj.save_journal([])

    result = tj.record_sell('华天酒店', '000428', 5.0)

    assert result is not None  # WR-07: 成功返回 pf (与拒绝的 None 区分)
    rest = tj.load_portfolio()
    assert [p['code'] for p in rest['positions']] == ['003040']  # 楚天龙保留
    # 2026-09-17 口径变更(承用户 2026-09-15 "账本只记持仓不记现金"):
    # record_sell 不再维护 cash —— 原断言 "cash 增加该笔 proceeds" 已失效
    assert rest['cash'] == 10000.0
    sells = [e for e in tj.load_journal() if e['action'] == 'SELL']
    assert len(sells) == 1
    assert sells[0]['code'] == '000428' and sells[0]['shares'] == 100


def test_record_sell_same_code_merges_all_lots_keeps_other_stock(ledger_files):
    """WR-02 (2026-09-03 语义保持): 同码多批整仓卖合并全部批次, 他股不动。"""
    pf = _two_position_pf()
    pf['positions'] = [
        {'name': '楚天龙', 'code': '003040', 'buy_date': '2026-08-25',
         'buy_price': 14.0, 'shares': 100},
        {'name': '楚天龙', 'code': '003040', 'buy_date': '2026-08-26',
         'buy_price': 16.0, 'shares': 200},
        {'name': '华天酒店', 'code': '000428', 'buy_date': '2026-09-02',
         'buy_price': 4.5, 'shares': 100},
    ]
    pf['position'] = pf['positions'][0]
    tj.save_portfolio(pf)
    tj.save_journal([])

    result = tj.record_sell('楚天龙', '003040', 18.0)

    assert result is not None  # WR-07: 成功返回 pf (与拒绝的 None 区分)
    rest = tj.load_portfolio()
    assert [p['code'] for p in rest['positions']] == ['000428']
    sells = [e for e in tj.load_journal() if e['action'] == 'SELL']
    assert len(sells) == 1
    assert sells[0]['shares'] == 300  # 两批合并单笔
    assert sells[0]['buy_date'] == '2026-08-25'  # 最早批日期


def test_record_sell_typo_code_falls_back_to_unambiguous_name(ledger_files):
    """WR-02: code 无命中 (手滑码) -> 退回 name 全等匹配; 名字唯一 -> 正常卖。"""
    pf = _two_position_pf()
    tj.save_portfolio(pf)
    tj.save_journal([])

    result = tj.record_sell('华天酒店', '00042', 5.0)  # 码缺位 -> 无 code 命中

    assert result is not None  # WR-07: name 回退成功同样返回 pf
    rest = tj.load_portfolio()
    assert [p['code'] for p in rest['positions']] == ['003040']
    assert tj.load_journal()[0]['code'] == '000428'  # SELL 记实际持仓码, 非手滑 argv


def test_record_sell_refusal_returns_none_no_match_and_legacy(ledger_files, capsys):
    """WR-07: 其余两条拒绝路径同样返回 None (调用方以 None 判定拒绝 -> 非零退出):
    ① positions 列表内名码双不中 (无该股)  ② 旧格式单仓 (无 positions 键) 名码双不中。
    两条路径都零落账 (文件字节不变, 日志零 SELL)。
    """
    # ① positions 列表: code 无命中 + name 无命中 -> 拒绝
    pf = _two_position_pf()
    tj.save_portfolio(pf)
    tj.save_journal([])

    result = tj.record_sell('楚天隆', '999999', 5.0)  # 名码都打不中任何持仓

    assert result is None  # WR-07: 拒绝返回 None
    assert 'WARNING' in capsys.readouterr().out
    assert tj.load_portfolio() == pf  # 拒绝 = 零改动 (文件内容不变)
    assert tj.load_journal() == []

    # ② 旧格式 (仅 position 单仓, 无 positions 键): 名码双不中 -> 拒绝
    legacy = {'cash': 10000.0, 'total_trades': 0, 'winning_trades': 0, 'total_pnl': 0.0,
              'position': {'name': '楚天龙', 'code': '003040', 'buy_date': '2026-09-01',
                           'buy_price': 15.0, 'shares': 100}}
    tj.save_portfolio(legacy)
    tj.save_journal([])

    result = tj.record_sell('不存在名', '999999', 5.0)

    assert result is None  # WR-07: 旧格式拒绝同样返回 None
    assert 'WARNING' in capsys.readouterr().out
    assert tj.load_portfolio() == legacy  # 拒绝 = 零改动 (文件内容不变)
    assert tj.load_journal() == []


# ---------- WR-03 (04 修复): 读者碰撞 PermissionError 短重试 (api/jobs.py write_job 模板) ----------

def test_replace_permissionerror_collision_retries_then_succeeds(ledger_files, monkeypatch):
    """首 2 次 replace 撞读者句柄 (PermissionError) -> 重试后成功, 内容完整, 零 .tmp。"""
    pf_path, _ = ledger_files
    real_replace = os.replace
    state = {"calls": 0}

    def flaky_replace(src, dst):
        state["calls"] += 1
        if state["calls"] <= 2:
            raise PermissionError("simulated reader collision (WR-03)")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)

    pf = {"positions": [{"code": "003040", "name": "楚天龙"}], "cash": 1415.5}
    tj.save_portfolio(pf)

    assert state["calls"] == 3  # 两次碰撞 + 一次成功
    assert json.loads(pf_path.read_text(encoding="utf-8")) == pf
    assert list(pf_path.parent.glob("*.tmp")) == []  # 成功路径零 .tmp 残留


def test_replace_persistent_permissionerror_exhausts_keeps_old_target(ledger_files, monkeypatch):
    """4 次全撞 -> PermissionError 上抛 (不无限重试); 目标保持上次已提交内容。"""
    pf_path, _ = ledger_files
    good = {"positions": [], "cash": 1000.0}
    pf_path.write_bytes(_serialize(good))

    def always_permission_error(src, dst):
        raise PermissionError("persistent reader collision (WR-03)")

    monkeypatch.setattr(os, "replace", always_permission_error)

    with pytest.raises(PermissionError):
        tj.save_portfolio({"positions": [{"code": "003040", "name": "楚天龙"}], "cash": 1415.5})

    assert pf_path.read_bytes() == _serialize(good)  # 目标 = 旧内容 (D-04 失败语义不变)
