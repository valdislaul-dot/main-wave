"""
K线格式统一迁移 (2026-08-14)
历史遗留: 搜狐volume_lots(手) + 新浪/腾讯 volume(股) 混合格式
统一为: 每行都有 volume(股), volume_lots 保留(真VWAP计算仍用)
- 逐行: volume缺失/为0时用 volume_lots×100 补填
- 幂等: 已统一的文件重跑无副作用
用法: python migrate_kline_format.py
"""
import json, os, glob, sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')


def migrate_file(path):
    """返回 (转换行数, 总行数)"""
    with open(path, encoding='utf-8') as f:
        raw = json.load(f)
    is_dict = isinstance(raw, dict) and 'data' in raw
    rows = raw['data'] if is_dict else raw
    if not isinstance(rows, list):
        return 0, 0
    converted = 0
    for k in rows:
        if not isinstance(k, dict):
            continue
        v = k.get('volume')
        if v in (None, 0) and k.get('volume_lots'):
            k['volume'] = round(k['volume_lots'] * 100, 2)
            converted += 1
        elif v is not None:
            k['volume'] = float(v)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False)
    return converted, len(rows)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    files = sorted(glob.glob(os.path.join(KLINE_DIR, '*.json')))
    junk = [f for f in files if os.path.basename(f).startswith('._')]
    for j in junk:
        try:
            os.remove(j)
            print(f'[清理] 删除mac垃圾文件: {os.path.basename(j)}')
        except Exception as e:
            print(f'[清理] 失败 {j}: {e}')
    files = [f for f in files if not os.path.basename(f).startswith('._')]

    total_files = total_conv = total_rows = 0
    for fp in files:
        try:
            c, n = migrate_file(fp)
        except UnicodeDecodeError:
            with open(fp, encoding='gbk') as f:
                raw = json.load(f)
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(raw, f, ensure_ascii=False)
            c, n = migrate_file(fp)
        except Exception as e:
            print(f'[跳过] {os.path.basename(fp)}: {e}')
            continue
        total_files += 1
        total_conv += c
        total_rows += n
    print(f'[迁移完成] 文件 {total_files} 个 | 总行数 {total_rows:,} | 补填volume {total_conv:,} 行')


if __name__ == '__main__':
    main()
