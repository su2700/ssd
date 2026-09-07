@echo off
chcp 65001 >nul
title 安装 Ext4 一键挂载小工具桌面快捷方式
cd /d "%~dp0"

echo 正在为您在 Windows 桌面创建快捷方式...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\create_desktop_shortcut.ps1"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo  [OK] 安装成功！已在桌面生成 "Ext4-Mounter" 快捷方式！
    echo  您可以直接在桌面双击启动小工具。
    echo ========================================================
) else (
    echo.
    echo [ERROR] 创建快捷方式失败，请右键此脚本选择 "以管理员身份运行" 重试。
)

echo.
pause
