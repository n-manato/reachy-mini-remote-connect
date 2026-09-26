@echo off
rem One-time setup: Python check/install, .venv, packages, robot connection test.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo Setup did not finish. Read the messages above, fix the problem and run setup.bat again.
) else (
    echo.
    echo Setup finished. Double-click run.bat to start.
)
pause
