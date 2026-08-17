"""
数据备份打包 — Win端→Mac端
打包: K线数据 + 涨停池快照
输出: 桌面/main-wave-data-YYYYMMDD.zip (跨平台兼容)
"""

import os, sys, zipfile, json
from datetime import datetime
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")


def make_backup():
    date_tag = datetime.now().strftime('%Y%m%d')
    out_path = os.path.join(DESKTOP, f'main-wave-data-{date_tag}.zip')

    # ── 要打包的项目 ──
    items = [
        # (源路径, zip内名称, 说明)
        ('data/zt_pool', 'zt_pool', '涨停池快照'),
        ('data/stock_data.json', 'stock_data.json', '核心K线(静态历史)'),
        ('data/kline_data', 'kline_data', 'K线数据(3180只)'),
        ('data/auction', 'auction', '竞价快照'),
        ('data/industry_map.json', 'industry_map.json', '行业映射'),
        ('logs/candidates_*.json', 'candidates', '候选记录'),
    ]

    total_files = 0
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for src, arcname, desc in items:
            src_path = os.path.join(BASE, src)
            if '*' in src:
                # glob pattern
                import glob
                for f in sorted(glob.glob(src_path)):
                    arc = os.path.join(arcname, os.path.basename(f))
                    zf.write(f, arc)
                    total_files += 1
            elif os.path.isdir(src_path):
                for root, dirs, files in os.walk(src_path):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        rel = os.path.relpath(fpath, src_path)
                        arc = os.path.join(arcname, rel)
                        zf.write(fpath, arc)
                        total_files += 1
            elif os.path.exists(src_path):
                zf.write(src_path, os.path.join(arcname, os.path.basename(src_path)))
                total_files += 1
            else:
                print(f"  [SKIP] {desc}: 路径不存在")

        # 加一个说明文件
        readme = (
            f"main-wave 数据备份\n"
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"来源: Win端\n"
            f"文件数: {total_files}\n"
            f"\nMac端恢复方式:\n"
            f"  1. 解压到 ~/Desktop/gogo/data/ 对应目录\n"
            f"  2. 路径分隔符已统一为 / (zip标准)\n"
            f"  3. JSON编码统一为 UTF-8\n"
        )
        zf.writestr('README.txt', readme.encode('utf-8'))

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f"[Backup] 完成: {out_path}")
    print(f"[Backup] {total_files}个文件, {size_mb:.1f}MB")

    zt_dir = os.path.join(BASE, 'data', 'zt_pool')
    zt_files = len(os.listdir(zt_dir)) if os.path.exists(zt_dir) else 0
    print(f"[Backup] 内含: ZT{zt_files}天")

    return out_path


if __name__ == '__main__':
    make_backup()
