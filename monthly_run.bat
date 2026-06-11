@echo off
rem ============================================================
rem  Parking Perks - automated monthly draw
rem  Used by Task Scheduler trigger "Daily 06:30".
rem  Exits instantly if the previous month is already drawn+reported.
rem  Output is appended to backend\data\monthly_run.log by the script itself.
rem ============================================================
cd /d "%~dp0backend"

rem Rebuild the venv if it's broken/copied from another machine
if exist .venv (
  .venv\Scripts\python -c "import sys" >nul 2>&1
  if errorlevel 1 rmdir /s /q .venv
)

if not exist .venv (
  python -m venv .venv || exit /b 1
  .venv\Scripts\python -m pip install --upgrade pip -q
  .venv\Scripts\python -m pip install -r requirements.txt -q || exit /b 1
)

.venv\Scripts\python monthly_run.py %*
