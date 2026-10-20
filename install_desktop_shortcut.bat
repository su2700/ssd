@echo off
setlocal
title Install Ext4-Mounter desktop shortcut
echo Creating the Ext4-Mounter desktop shortcut...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\create_desktop_shortcut.ps1"
if errorlevel 1 (
    echo [ERROR] Shortcut creation failed. Check the message above.
    pause
    exit /b 1
)
echo [OK] Ext4-Mounter shortcut created on your desktop.
pause
exit /b 0
