@echo off
REM 작업 스케줄러가 부르는 진입점. 예: run.bat decide
cd /d "%~dp0"
if not exist work mkdir work
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
REM 실행 종류마다 로그를 따로 씀. 한 파일을 같이 쓰면 장중 감시가 파일을 잡고 있어 판단 실행이 바로 실패함
.venv\Scripts\python.exe run.py %* >> work\%1.log 2>&1
