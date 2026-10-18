$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required." }
}
$dependencyCheck = @'
from importlib.metadata import version
from pathlib import Path
try:
    specs = [line.strip().split('==') for name in ('requirements-desktop.txt', 'requirements-asset-manager.txt')
             for line in Path(name).read_text(encoding='utf-8').splitlines() if '==' in line]
    ready = all(version(name) == wanted for name, wanted in specs)
except Exception:
    ready = False
raise SystemExit(0 if ready else 1)
'@
& $python -c $dependencyCheck
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install -r requirements-desktop.txt
    if ($LASTEXITCODE -ne 0) { throw "Desktop dependency installation failed." }
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot ".game\save-id"))) {
    & $python -X utf8 -B -m tools.playable.setup_local
    if ($LASTEXITCODE -ne 0) { throw "Save initialization failed; existing files preserved." }
}
$pythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
Start-Process -FilePath $pythonw -ArgumentList @('-X','utf8','-m','tools.playable.desktop') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
