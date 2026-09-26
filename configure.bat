@echo off
rem Change the robot (paste a new connection code) and test the connection.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m reachy_kit.configure
pause
