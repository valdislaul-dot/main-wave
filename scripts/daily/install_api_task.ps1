# ============================================
#  Install Windows scheduled task: gogo-api
#  Registers the resident API service autostart:
#  runs <repo>\run_api.bat about 5 minutes after system startup
#  Idempotent - safe to re-run (unregister then register -Force)
#  NOTE: must run from an ELEVATED PowerShell - registering tasks in the
#  root folder is denied for non-elevated users on this machine (0x80070005)
# ============================================

# Path derivation exclusively from $PSScriptRoot (this file lives in scripts/daily/)
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$BatPath = Join-Path $RepoRoot "run_api.bat"

# Transcript echo: proves the paths came from $PSScriptRoot, not a hardcoded literal
Write-Output "Resolved repo root: $RepoRoot"
Write-Output "Resolved bat path:  $BatPath"

$TaskName = "gogo-api"

# Remove existing task if any (idempotency: a second run replaces, never stacks)
try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}

# Create task action: cmd.exe /c "<repo>\run_api.bat" with WorkingDirectory = repo root
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatPath`"" -WorkingDirectory $RepoRoot

# Trigger: exactly ONE - At system startup with a 5-minute delay for network readiness.
# NOTE: PS 5.1's -RandomDelay parameter is silently dropped for boot triggers (the
# machine's CIM provider cannot model it, and the task XML schema rejects <RandomDelay>
# inside <BootTrigger> - verified against both Register-ScheduledTask -Xml and schtasks).
# The schema-supported equivalent is the fixed <Delay>PT5M</Delay>, set directly below.
$Trigger1 = New-ScheduledTaskTrigger -AtStartup
$Trigger1.Delay = 'PT5M'

# Settings: convention shape plus unlimited execution time limit (PT0S) so Task
# Scheduler's default 3-day limit can never terminate the resident service
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

# Principal: current interactive user, limited privileges (never SYSTEM, never Highest)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger1 `
    -Settings $Settings `
    -Principal $Principal `
    -Description "gogo API resident service: FastAPI /health liveness" `
    -Force

Write-Output "Registered task: $TaskName (AtStartup + 5-minute fixed delay)"
Write-Output "Next step: Start-ScheduledTask -TaskName gogo-api"
