@echo off
rem One-time setup: create .venv and install the Reachy Mini SDK.
cd /d "%~dp0"
python -m venv .venv || goto :error
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :error
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
if not exist robot_config.json copy robot_config.example.json robot_config.json >nul
echo.
echo Setup finished. Fill in robot_config.json, connect GlobalProtect, then run run.bat
pause
exit /b 0

:error
echo.
echo Setup failed. Make sure Python 3.11 - 3.13 (64-bit) is installed and on PATH.
pause
exit /b 1
