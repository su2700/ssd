@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -AsAdmin
if errorlevel 1 (
    pause
    exit /b 1
)
exit /b 0
