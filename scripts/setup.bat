@echo off
rem Creates .venv-app in the repository root and installs HandPilot's dependencies (needs internet once).
rem For a ready-to-run build that needs no installation see tools\portable\.
cd /d "%~dp0.."
if not exist .venv-app\Scripts\python.exe (
    py -3.12 -m venv .venv-app || python -m venv .venv-app
)
.venv-app\Scripts\python.exe -m pip install --upgrade pip
.venv-app\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo Done. Start HandPilot with scripts\run.bat
