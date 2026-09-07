@echo off
chcp 65001 >nul
title Ext4 一键挂载小工具
cd /d "%~dp0"

where pythonw >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    start "" pythonw main.py
) else (
    start "" python main.py
)
