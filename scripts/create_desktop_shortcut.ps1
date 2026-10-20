# Create Desktop Shortcut for Ext4 One-Click Mounter
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$mainPy = Join-Path $projectRoot "main.py"

$pythonCmd = (Get-Command pythonw.exe -ErrorAction SilentlyContinue)
if (-not $pythonCmd) {
    $pythonCmd = (Get-Command python.exe -ErrorAction SilentlyContinue)
}
if (-not $pythonCmd) {
    throw 'Python 3.8+ was not found. Install Python, add it to PATH, and run this installer again.'
}
$pythonExe = $pythonCmd.Source

$desktop = [Environment]::GetFolderPath("Desktop")
if (-not (Test-Path $desktop)) {
    $desktop = Join-Path $env:USERPROFILE "Desktop"
}

$shortcutPath = Join-Path $desktop "Ext4-Mounter.lnk"

$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonExe
$shortcut.Arguments = "`"$mainPy`""
$shortcut.WorkingDirectory = "$projectRoot"
$shortcut.Description = "Ext4 SSD and Image One-Click Mounter for Windows"
$shortcut.Save()

Write-Host "Desktop shortcut created successfully at: $shortcutPath"
