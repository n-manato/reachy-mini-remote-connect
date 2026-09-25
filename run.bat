@echo off
rem Connect to the robot in robot_config.json (GlobalProtect must be connected).
cd /d "%~dp0"
.venv\Scripts\python.exe reachy_connect.py
