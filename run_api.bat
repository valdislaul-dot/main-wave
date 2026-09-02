@echo off
cd /d "%~dp0"
if not exist logs\api mkdir logs\api
set PYTHONUTF8=1
python -m api.main >> logs\api\console.log 2>&1
