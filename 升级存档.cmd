@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
".venv\Scripts\python.exe" -X utf8 -m tools.windows_desktop --upgrade
if errorlevel 1 (echo Upgrade failed. Existing saves were preserved.) else (echo Upgrade complete.)
pause
