param([switch]$AsAdmin)
$ErrorActionPreference = 'Stop'

try {
    if ($AsAdmin) {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
            $child = Start-Process -FilePath "$PSHOME\powershell.exe" -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f $PSCommandPath), '-AsAdmin'
            )
            exit $child.ExitCode
        }
    }

    $projectRoot = Split-Path -Parent $PSScriptRoot
    $python = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command python.exe -ErrorAction SilentlyContinue }
    if (-not $python) {
        throw "Problem: Python was not found.`nCause: The source version of Ext4-Mounter needs Python 3.8+ with Tcl/Tk.`nFix: Install Python from https://www.python.org/downloads/windows/ with 'Add Python to PATH' and 'tcl/tk and IDLE' enabled. Reopen the launcher and recreate the desktop shortcut, or use the standalone EXE."
    }
    $consolePython = Join-Path (Split-Path -Parent $python.Source) 'python.exe'
    if (Test-Path -LiteralPath $consolePython) {
        & $consolePython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 2)'
        if ($LASTEXITCODE -ne 0) {
            throw "Problem: Python is incompatible.`nCause: This app requires Python 3.8 or newer.`nFix: Install a supported Python from https://www.python.org/downloads/windows/ and recreate the desktop shortcut."
        }
        $tkProbe = @'
import sys
try:
    import tkinter
except Exception:
    sys.exit(1)
'@
        & $consolePython -c $tkProbe
        if ($LASTEXITCODE -ne 0) {
            throw "Problem: Tcl/Tk is missing.`nCause: The Python GUI component could not be imported.`nFix: Modify/Repair Python and enable 'tcl/tk and IDLE', then verify with python -m tkinter."
        }
    }
    Start-Process -FilePath $python.Source -WorkingDirectory $projectRoot -ArgumentList ('"{0}"' -f (Join-Path $projectRoot 'main.py'))
} catch {
    $detail = "Ext4-Mounter could not start.`n`n$($_.Exception.Message)`n`nIf administrator authorization was cancelled, retry and allow UAC. If launch is blocked by device policy, contact your administrator."
    Write-Host "[ERROR] $detail"
    try {
        $dialog = New-Object -ComObject WScript.Shell
        [void]$dialog.Popup($detail, 0, 'Ext4-Mounter - Startup error', 16)
    } catch {
        Write-Host '[ERROR] The error dialog could not be displayed. See the console message above.'
    }
    exit 1
}
