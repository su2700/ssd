@echo off
chcp 65001 >nul
title 打包 Ext4-Mounter 为独立 exe
cd /d "%~dp0\.."

echo 正在检查 PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo 未安装 pyinstaller，正在为您自动安装...
    python -m pip install pyinstaller
)

echo 正在编译生成单个独立可执行文件 (Ext4-Mounter.exe)...
pyinstaller --noconsole --onefile --clean --name "Ext4-Mounter" main.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo  [OK] 打包成功！生成的独立 exe 位于:
    echo  %~dp0..\dist\Ext4-Mounter.exe
    echo ========================================================
) else (
    echo [ERROR] 打包失败，请检查上方日志。
)

pause
