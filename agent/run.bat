@echo off
REM 작업 스케줄러가 부르는 진입점. 예: run.bat decide
cd /d "%~dp0"
if not exist work mkdir work
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe run.py %* >> work\agent.log 2>&1
