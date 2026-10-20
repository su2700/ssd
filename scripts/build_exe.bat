@echo off
setlocal
title Build Ext4-Mounter
pushd "%~dp0.."
if errorlevel 1 exit /b 1
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 goto failed
)
python -m PyInstaller --noconsole --onefile --clean --name "Ext4-Mounter" main.py
if errorlevel 1 goto failed
echo [OK] Build completed: dist\Ext4-Mounter.exe
popd
pause
exit /b 0
:failed
echo [ERROR] Build failed. Check the message above.
popd
pause
exit /b 1
