# ============================================
#  安装Windows定时任务：每日选股流水线
#  开机后自动运行 + 每日15:30定时运行
#  以管理员身份运行此脚本
# ============================================

$TaskName = "主升浪每日选股流水线"
$ScriptPath = "C:\Users\Davis\Desktop\主升浪\scripts\daily\auto_start.bat"
$WorkingDir = "C:\Users\Davis\Desktop\主升浪\scripts\daily"

# Remove existing task if any
try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}

# Create task action
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$ScriptPath`"" -WorkingDirectory $WorkingDir

# Trigger 1: At system startup (with 5 min delay for network)
$Trigger1 = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Minutes 5)

# Trigger 2: Daily at 15:30 (after market close)
$Trigger2 = New-ScheduledTaskTrigger -Daily -At "15:30"

# Settings: run even if on battery, retry on failure
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

# Register task for current user
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger1, $Trigger2 `
    -Settings $Settings `
    -Principal $Principal `
    -Description "每日盘后自动下载K线数据并筛选明日涨停候选标的" `
    -Force

Write-Host "============================================" -ForegroundColor Green
Write-Host "  定时任务已安装!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  任务名称: $TaskName"
Write-Host "  运行时间: 开机后5分钟 + 每日15:30"
Write-Host "  脚本路径: $ScriptPath"
Write-Host "  日志位置: C:\Users\Davis\Desktop\主升浪\logs\pipeline.log"
Write-Host ""
Write-Host "  手动运行测试:"
Write-Host "    cd C:\Users\Davis\Desktop\主升浪\scripts\daily"
Write-Host "    python run_pipeline.py"
Write-Host ""
Write-Host "  查看任务: taskschd.msc"
