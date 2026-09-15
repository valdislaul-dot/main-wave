@echo off
REM ============================================
REM  每日选股流水线 - 开机自动运行
REM  盘后(15:00后)自动下载数据并筛选候选
REM ============================================

REM BASE 由脚本自身位置推导（本文件在 scripts\daily\，上两级即仓库根目录）。
REM 禁止改回硬编码绝对路径：该路径已因仓库搬家失效两次（主升浪→gogo→项目\gogo），
REM 见 .planning/.../01-PATTERNS.md 的 D-09 约定。
for %%i in ("%~dp0..\..") do set "BASE=%%~fi"
set "LOG=%BASE%\logs\pipeline.log"

echo [%date% %time%] Pipeline starting... >> "%LOG%"

cd /d "%BASE%\scripts\daily"
python run_pipeline.py >> "%LOG%" 2>&1

echo [%date% %time%] Pipeline complete. >> "%LOG%"
