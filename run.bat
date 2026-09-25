@echo off
rem Connect to the robot in robot_config.json and run an app (GlobalProtect must be connected).
rem   run.bat                                 runs my_app.py
rem   run.bat examples\all_features_app.py    runs another app
cd /d "%~dp0"
.venv\Scripts\python.exe -m reachy_kit.launcher %*
