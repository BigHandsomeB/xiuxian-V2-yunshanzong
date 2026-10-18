$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required." }
}
& $python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required." }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
$save = Join-Path $PSScriptRoot ".game"
if (-not (Test-Path -LiteralPath (Join-Path $save "save-id"))) {
    & $python -X utf8 -B -m tools.playable.setup_local
    if ($LASTEXITCODE -ne 0) { throw "Save initialization failed; existing files were preserved." }
}
if (-not $env:ASSET_MANAGER_TOKEN) {
    $env:ASSET_MANAGER_TOKEN = & $python -c "import secrets; print(secrets.token_urlsafe(32))"
}
$env:GAME_LOCAL_HTTP = "1"
Write-Host "Game: http://127.0.0.1:8000/game/"
Write-Host "Login token: $env:ASSET_MANAGER_TOKEN"
Write-Host "Keep this window open. Press Ctrl+C to stop."
& $python -X utf8 -B -m tools.playable.server
