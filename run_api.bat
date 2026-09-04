@echo off
cd /d "%~dp0"
if not exist logs\api mkdir logs\api
rem OPS-03 log rotation (D-32, 05-04 live M-B adaptation): rotation must happen
rem before python starts. cmd keeps its OWN copy of the >> handle (no
rem FILE_SHARE_WRITE / FILE_SHARE_DELETE) for the child's whole lifetime
rem (verified live 2026-09-05: in-process rename hits WinError 32, reopen hits
rem Errno 13) - the only unheld moment is right here. Threshold 5242880 =
rem 5*1024*1024, kept in sync with api/log_housekeep.py MAX_CONSOLE_LOG_BYTES
rem (the two comments cross-reference). ASCII-only: cmd parses this file in
rem the OEM codepage; non-ASCII bytes and LF-only endings break line parsing.
if exist "logs\api\console.log" for %%A in ("logs\api\console.log") do if %%~zA GTR 5242880 move /y "logs\api\console.log" "logs\api\console.log.1" >nul
set PYTHONUTF8=1
python -m api.main >> logs\api\console.log 2>&1
