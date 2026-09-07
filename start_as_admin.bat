@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Check for administrative rights
net session >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    start "" python main.py
) else (
    powershell -NoProfile -Command "Start-Process cmd.exe -ArgumentList '/c cd /d \"%~dp0\" && python main.py' -Verb RunAs"
)
