@echo off
rem Starts HandPilot without a console window (tray icon appears). Extra arguments are passed on.
cd /d "%~dp0.."
start "" .venv-app\Scripts\pythonw.exe HandPilot.pyw %*
