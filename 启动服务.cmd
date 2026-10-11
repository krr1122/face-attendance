@echo off
set "PYTHONUTF8=1"
cd /d "%~dp0"
"D:\anaconda\envs\ai_data\python.exe" app.py serve
if errorlevel 1 pause
