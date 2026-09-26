@echo off
rem One-time setup: Python check/install, .venv, packages, robot connection test.
cd /d "%~dp0"
rem The built-in Windows PowerShell 5.1, not whatever "powershell" comes first on PATH.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
    echo.
    echo Setup did not finish. Read the messages above, fix the problem and run setup.bat again.
) else (
    echo.
    echo Setup finished. Double-click run.bat to start.
)
pause
