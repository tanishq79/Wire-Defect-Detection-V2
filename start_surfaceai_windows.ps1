# Daily Windows launcher. It does not check Git or download updates.
param([ValidateRange(1, 65535)][int]$Port = 8000)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".surfaceai-venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "SurfaceAI is not installed yet. Run .\setup_surfaceai_windows.ps1 once first."
}

Set-Location $ProjectRoot
& $Python run_desktop.py --port $Port
