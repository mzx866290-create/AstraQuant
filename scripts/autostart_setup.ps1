# Register Windows task: start the Docker Compose stack after login.
# The startup script also restores the local Vite dev frontend on 127.0.0.1:5173.
# Run as administrator: powershell -ExecutionPolicy Bypass -File scripts\autostart_setup.ps1

$TaskName = "StockPlatformAutoStart"
$ScriptPath = Join-Path $PSScriptRoot "start_docker_stack.ps1"
$PowerShellExe = (Get-Command powershell -ErrorAction SilentlyContinue).Source
if (-not $PowerShellExe) { $PowerShellExe = "powershell" }

Write-Host "============================================"
Write-Host " Stock Platform - Register Auto-Start Task"
Write-Host "============================================"
Write-Host "Task:   $TaskName"
Write-Host "Shell:  $PowerShellExe"
Write-Host "Script: $ScriptPath"
Write-Host ""

# Remove existing task
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Create action. This starts the Docker stack and the local frontend dev server.
# It does not start the local SQLite development backend services.
$Action = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
    -WorkingDirectory (Split-Path $ScriptPath -Parent | Split-Path -Parent)

# Trigger: on logon with delay so Docker Desktop has time to boot.
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Trigger.Delay = "PT90S"

# Settings
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)

# Register. Highest run level is preferred, but it needs admin rights. Fall
# back to a normal per-user task so autostart still works for this machine.
$Registered = $false
$RegistrationMethod = ""
try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Highest -Force -ErrorAction Stop | Out-Null
    $Registered = $true
    $RegistrationMethod = "scheduled-task-highest"
    Write-Host "[OK] Registered with highest run level." -ForegroundColor Green
} catch {
    Write-Host "[WARN] Highest run level registration failed; retrying as current user." -ForegroundColor Yellow
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force -ErrorAction Stop | Out-Null
        $Registered = $true
        $RegistrationMethod = "scheduled-task-current-user"
    } catch {
        Write-Host "[WARN] Task Scheduler registration failed; creating Startup shortcut." -ForegroundColor Yellow
        $StartupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
        New-Item -ItemType Directory -Force -Path $StartupDir | Out-Null
        $ShortcutPath = Join-Path $StartupDir "$TaskName.lnk"
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $PowerShellExe
        $Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
        $Shortcut.WorkingDirectory = (Split-Path $ScriptPath -Parent | Split-Path -Parent)
        $Shortcut.WindowStyle = 7
        $Shortcut.Description = "Start Stock Platform Docker stack"
        $Shortcut.Save()
        $Registered = Test-Path $ShortcutPath
        if ($Registered) {
            $RegistrationMethod = "startup-shortcut"
            Write-Host "[OK] Startup shortcut created: $ShortcutPath" -ForegroundColor Green
        }
    }
}

if ($Registered) {
    Write-Host ""
    Write-Host "[OK] Auto-start registered via $RegistrationMethod. Services will auto-start on next login." -ForegroundColor Green
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  Run now: powershell -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    if ($RegistrationMethod -like "scheduled-task*") {
        Write-Host "  View:    Get-ScheduledTask -TaskName '$TaskName'"
        Write-Host "  Run:     Start-ScheduledTask -TaskName '$TaskName'"
        Write-Host "  Remove:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
    } else {
        Write-Host "  View:    Get-Item `"$ShortcutPath`""
        Write-Host "  Remove:  Remove-Item `"$ShortcutPath`""
    }
} else {
    Write-Host "[ERROR] Failed to register task." -ForegroundColor Red
}
