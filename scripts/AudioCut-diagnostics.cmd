@echo off
setlocal
set "APP_ROOT=%~dp0.."
if exist "%APP_ROOT%\release\AudioCut\AudioCut.exe" (
  start "" "%APP_ROOT%\release\AudioCut\AudioCut.exe" --diagnose-audio %*
  exit /b 0
)
set "APP_PYTHON=%APP_ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%APP_ROOT%\..\.venv\Scripts\pythonw.exe"
if not exist "%APP_PYTHON%" (
  echo Python environment missing. See README.md for setup.
  pause
  exit /b 1
)
start "" "%APP_PYTHON%" "%APP_ROOT%\app.py" --diagnose-audio %*
