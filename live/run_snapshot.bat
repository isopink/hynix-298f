@echo off
REM Run weekdays 08:25 via Task Scheduler (see README)
cd /d "%~dp0"
python snapshot.py --loop >> snapshot.log 2>&1
