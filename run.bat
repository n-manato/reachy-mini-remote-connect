@echo off
rem Connect to the robot in robot_config.json and run an app (GlobalProtect must be connected).
rem   run.bat                                 runs my_app.py
rem   run.bat examples\all_features_app.py    runs another app
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo This PC is not set up yet: double-click setup.bat first.
    pause
    exit /b 1
)
if not exist "robot_config.json" (
    echo No robot configured yet.
    .venv\Scripts\python.exe -m reachy_kit.configure || (pause & exit /b 1)
)
.venv\Scripts\python.exe -m reachy_kit.launcher %*
