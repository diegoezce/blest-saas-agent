@echo off
REM ── Blest worker launcher for Windows Task Scheduler ───────────────────────
REM Runs the two-phase worker (enrichment + Zoho push) once.
REM Schedule this .bat daily (see CLAUDE.md → Windows Worker).
REM Logs rotate weekly: worker_task_YYYY-Www.log (8 weeks kept).

cd /d "%~dp0.."

REM Build a weekly log filename: worker_task_2026-W29.log
for /f %%i in ('powershell -NoProfile -Command "Get-Date -UFormat '%%Y-W%%V'"') do set WEEK=%%i
set LOGFILE=%~dp0worker_task_%WEEK%.log

REM Delete log files older than 8 weeks (56 days)
forfiles /p "%~dp0" /m "worker_task_*.log" /d -56 /c "cmd /c del @path" 2>nul

py -3.11 "%~dp0worker.py" >> "%LOGFILE%" 2>&1
