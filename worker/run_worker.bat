@echo off
REM ── Blest worker launcher for Windows Task Scheduler ───────────────────────
REM Runs the two-phase worker (enrichment + Zoho push) once.
REM Schedule this .bat daily (see CLAUDE.md → Windows Worker).
REM Uses the py launcher so it works regardless of Task Scheduler's PATH.

cd /d "%~dp0.."
py -3.11 "%~dp0worker.py" >> "%~dp0worker_task.log" 2>&1
