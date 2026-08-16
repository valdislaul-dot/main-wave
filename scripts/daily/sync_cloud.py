"""
数据上云 (2026-08-16) — 盘后流水线完成后自动 git 同步关键快照到 GitHub
实现「本地采集 + 云端展示」的数据桥

用法:
  python sync_cloud.py             # add + commit + push
  python sync_cloud.py --no-push   # 只 add + commit, 不 push (本地测试)
  python sync_cloud.py --status    # 只看将同步哪些文件/变更

被同步的快照(云端面板只读这些, 不依赖 kline_data/网络):
  data/zt_pool_state.json          涨停池状态
  data/zt_pool_exit_log.json       离池记录
  data/auction_state.json          竞价状态汇总(含可买标的+评分)
  data/auction/*.json              每日竞价快照
  logs/portfolio.json              持仓(多持仓)
  logs/trading_journal.json        交易日志
  logs/trader_a.json               交易员A
  logs/recommendation_review.json  推荐回看
  logs/candidates_*.json           盘后候选评分
  logs/daily_recommendations/*.json 每日推荐
"""
import subprocess, sys, os, glob
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git(*args):
    return subprocess.run(['git', *args], cwd=BASE, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def sync_files():
    """返回需上云的快照文件(相对路径, 显式列出避免误提交)"""
    files = [
        'data/zt_pool_state.json',
        'data/zt_pool_exit_log.json',
        'data/auction_state.json',
        'data/active_pool.json',
        'logs/portfolio.json',
        'logs/trading_journal.json',
        'logs/trader_a.json',
        'logs/recommendation_review.json',
    ]
    files += [os.path.relpath(f, BASE) for f in glob.glob(os.path.join(BASE, 'data', 'auction', '*.json'))]
    files += [os.path.relpath(f, BASE) for f in glob.glob(os.path.join(BASE, 'logs', 'candidates_*.json'))
              if 'candidates_v' not in f]  # 排除旧格式 candidates_v*
    files += [os.path.relpath(f, BASE) for f in glob.glob(os.path.join(BASE, 'logs', 'daily_recommendations', '*.json'))]
    return sorted(f.replace('\\', '/') for f in set(files) if os.path.exists(f))


def sync(no_push=False):
    files = sync_files()
    if not files:
        print('[Sync] 无关键快照文件')
        return 0

    for f in files:
        _git('add', f)

    r = _git('status', '--porcelain', '--', *files)
    changed = [l for l in r.stdout.splitlines() if l.strip()]
    if not changed:
        print('[Sync] 无变更, 跳过')
        return 0

    print(f'[Sync] 变更 {len(changed)} 个文件:')
    for l in changed[:15]:
        print(f'  {l[:80]}')

    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    r = _git('commit', '-m', f'[auto] 数据快照同步 {ts}')
    if r.returncode != 0:
        print(f'[Sync] commit失败: {r.stderr.strip()[:200]}')
        return 1

    if no_push:
        print('[Sync] 已commit(未push)')
        return 0

    r = _git('push')
    if r.returncode != 0:
        print(f'[Sync] push失败: {r.stderr.strip()[:200]}')
        return 1
    print('[Sync] push完成 ✅')
    return 0


if __name__ == '__main__':
    if '--status' in sys.argv:
        for f in sync_files():
            print(f)
    else:
        sys.exit(sync(no_push='--no-push' in sys.argv))
