@echo off
rem ============================================================
rem  Parking Perks - automated monthly draw
rem  Used by Task Scheduler trigger "Daily 06:30".
rem  Exits instantly if the previous month is already drawn+reported.
rem ============================================================
cd /d "%~dp0backend"

if not exist .venv (
  python -m venv .venv || exit /b 1
  .venv\Scripts\python -m pip install --upgrade pip -q
  .venv\Scripts\python -m pip install -r requirements.txt -q || exit /b 1
)

.venv\Scripts\python monthly_run.py %*
