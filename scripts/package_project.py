"""
项目文件打包 — 不含K线数据
包含: scripts/ logs/ 资料/ data/(除K线目录) 根目录md/txt
排除: kline_data/ backtest_kline/ minute_kline/ .git/ __pycache__/ ._文件
输出: 桌面/main-wave-project-YYYYMMDD.zip
"""
import os
import zipfile
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")

EXCLUDE_DIRS = {
    'kline_data', 'backtest_kline', 'minute_kline',   # K线数据(1.3G+25M+24M)
    '.git', '__pycache__', '.claude',
    'zt_pool_history',    # 东财历史缓存(95/110空文件, 已弃用)
}
EXCLUDE_FILES = {'package_project.py'}


def main():
    date_tag = datetime.now().strftime('%Y%m%d')
    out_path = os.path.join(DESKTOP, f'main-wave-project-{date_tag}.zip')

    total = 0
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in os.listdir(BASE):
            if item in EXCLUDE_DIRS or item.startswith('.'):
                continue
            full = os.path.join(BASE, item)
            if os.path.isfile(full):
                if item in EXCLUDE_FILES:
                    continue
                zf.write(full, f'main-wave/{item}')
                total += 1
            elif os.path.isdir(full):
                for root, dirs, files in os.walk(full):
                    # 目录内排除
                    dirs[:] = [d for d in dirs
                               if d not in EXCLUDE_DIRS and not d.startswith('.')]
                    for fname in files:
                        if fname.startswith('._'):
                            continue
                        fpath = os.path.join(root, fname)
                        rel = os.path.relpath(fpath, BASE)
                        zf.write(fpath, f'main-wave/{rel}')
                        total += 1

        readme = (
            f"main-wave 项目文件打包 (不含K线数据)\n"
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"来源: Win端\n"
            f"文件数: {total}\n"
            f"排除: kline_data/ backtest_kline/ minute_kline/ .git/ __pycache__/\n"
        )
        zf.writestr('main-wave/README_PACKAGE.txt', readme.encode('utf-8'))

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    print(f'完成: {out_path}')
    print(f'{total}个文件, {size_mb:.1f}MB')


if __name__ == '__main__':
    main()
