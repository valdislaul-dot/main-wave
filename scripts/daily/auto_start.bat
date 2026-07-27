@echo off
REM ============================================
REM  每日选股流水线 - 开机自动运行
REM  盘后(15:00后)自动下载数据并筛选候选
REM ============================================

set BASE=C:\Users\Davis\Desktop\主升浪
set LOG=%BASE%\logs\pipeline.log

echo [%date% %time%] Pipeline starting... >> "%LOG%"

cd /d "%BASE%\scripts\daily"
python run_pipeline.py >> "%LOG%" 2>&1

echo [%date% %time%] Pipeline complete. >> "%LOG%"
