@echo off
REM ── Blest DB backup launcher for Windows Task Scheduler ────────────────────
REM Runs weekly (Sunday 03:00 recommended).
REM Schedule via admin shell:
REM   schtasks /Create /TN "BlestBackup" /TR "C:\path\to\worker\run_backup.bat" /SC WEEKLY /D SUN /ST 03:00 /F

cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
py -3.11 "%~dp0backup_db.py"
