@echo off
REM install_agent_keys.cmd —— 一键安装两个 agent 的 SSH 公钥
REM 作用：绕开「未签名脚本不允许运行」（AllSigned/Restricted 执行策略），并以管理员身份运行。
REM 用法：右键「以管理员身份运行」，或直接双击（会弹 UAC）。

setlocal
set "PS1=%~dp0install_agent_keys.ps1"

if not exist "%PS1%" (
    echo [错误] 找不到 %PS1%
    pause
    exit /b 1
)

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在请求管理员权限...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','\"%PS1%\"'"
    exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
echo.
pause
