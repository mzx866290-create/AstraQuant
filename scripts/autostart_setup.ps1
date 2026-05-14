# 注册 Windows 任务计划：开机自动启动股票平台本地服务
# 以管理员身份运行: powershell -ExecutionPolicy Bypass -File scripts\autostart_setup.ps1

$TaskName = "StockPlatformAutoStart"
$ScriptPath = Join-Path $PSScriptRoot "start_local.py"
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) { $PythonExe = "python" }

Write-Host "============================================"
Write-Host " Stock Platform - Register Auto-Start Task"
Write-Host "============================================"
Write-Host "Task:   $TaskName"
Write-Host "Python: $PythonExe"
Write-Host "Script: $ScriptPath"
Write-Host ""

# Remove existing task
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Create action
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory (Split-Path $ScriptPath -Parent | Split-Path -Parent)

# Trigger: on logon with 30s delay
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Trigger.Delay = "PT30S"

# Settings
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)

# Register
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Highest -Force

if ($?) {
    Write-Host ""
    Write-Host "[OK] Task registered. Services will auto-start on next login." -ForegroundColor Green
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  View:   Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Run:    Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
} else {
    Write-Host "[ERROR] Failed. Run as Administrator." -ForegroundColor Red
}
