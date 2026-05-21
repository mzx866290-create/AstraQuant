@echo off
REM 注册 Windows 任务计划：开机自动启动股票平台本地服务
REM 以管理员身份运行此脚本

set POWERSHELL_EXE=powershell
set SCRIPT_PATH=%~dp0start_docker_stack.ps1
set TASK_NAME=StockPlatformAutoStart
set WORK_DIR=%~dp0..

echo ============================================
echo  Stock Platform - 注册开机自启任务
echo ============================================
echo.
echo Task Name: %TASK_NAME%
echo Script:    %SCRIPT_PATH%
echo Work Dir:  %WORK_DIR%
echo.

REM 先删除已有同名任务（忽略不存在的错误）
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

REM 创建任务：用户登录时触发，延迟30秒启动（等网络就绪）
schtasks /Create ^
  /TN "%TASK_NAME%" ^
  /TR "\"%POWERSHELL_EXE%\" -NoProfile -ExecutionPolicy Bypass -File \"%SCRIPT_PATH%\"" ^
  /SC ONLOGON ^
  /DELAY 0001:30 ^
  /RL LIMITED ^
  /F

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] 任务已注册成功！下次登录 Windows 时服务会自动启动。
    echo.
    echo 管理命令：
    echo   查看: schtasks /Query /TN "%TASK_NAME%" /V
    echo   手动运行: schtasks /Run /TN "%TASK_NAME%"
    echo   删除: schtasks /Delete /TN "%TASK_NAME%" /F
) else (
    echo.
    echo [ERROR] 注册失败，请以管理员身份运行此脚本。
)

pause
