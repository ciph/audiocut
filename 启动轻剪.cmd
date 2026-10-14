@echo off
setlocal
if exist "%~dp0dist\AudioCut\AudioCut.exe" (
  start "" "%~dp0dist\AudioCut\AudioCut.exe" %*
  exit /b 0
)
set "APP_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%~dp0..\.venv\Scripts\pythonw.exe"
if not exist "%APP_PYTHON%" (
  echo Python environment missing. See README.md for setup.
  pause
  exit /b 1
)
start "" "%APP_PYTHON%" "%~dp0app.py" %*
