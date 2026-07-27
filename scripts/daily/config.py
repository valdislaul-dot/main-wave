"""项目配置 - 自动检测平台和路径"""
import os, sys, platform

# Project root: parent of scripts/daily/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
DAILY_DIR = os.path.join(PROJECT_ROOT, '每日收盘数据')
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
KLINE_DIR = os.path.join(DATA_DIR, 'kline_data')

# Ensure dirs exist
for d in [DATA_DIR, DAILY_DIR, LOG_DIR, KLINE_DIR]:
    os.makedirs(d, exist_ok=True)

# Platform
IS_MAC = platform.system() == 'Darwin'
IS_WIN = platform.system() == 'Windows'

# Shell alias setup
if IS_MAC:
    SHELL_RC = os.path.expanduser('~/.zshrc')
    ALIAS_CMD = f'alias cc="cd {PROJECT_ROOT} && claude"'
else:
    SHELL_RC = None
    ALIAS_CMD = None
