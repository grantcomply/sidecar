@echo off
title Serato Sidecar
cd /d "%~dp0"
python main.py
if %errorlevel% neq 0 (
    echo.
    echo Failed to launch. Make sure Python 3.10+ is installed and dependencies are set up:
    echo   pip install -r requirements.txt
    pause
)
