# First-time Windows setup. This script does not pull, reset, or modify Git history.
param([ValidateRange(1, 65535)][int]$Port = 8000)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

# Keep the Windows runtime separate from older project .venv folders. This
# makes a repaired Windows install deterministic and does not affect Pi setup.
$Python = Join-Path $ProjectRoot ".surfaceai-venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -m venv .surfaceai-venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv .surfaceai-venv
    } else {
        throw "Python was not found. Install 64-bit Python 3.11, then run this script again."
    }
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt
& $Python run_desktop.py --port $Port
