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
    if (-not $python) { throw 'Python 3.8+ was not found. Install Python and add it to PATH.' }
    Start-Process -FilePath $python.Source -WorkingDirectory $projectRoot -ArgumentList ('"{0}"' -f (Join-Path $projectRoot 'main.py'))
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)"
    exit 1
}
