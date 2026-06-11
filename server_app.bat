@echo off
rem ============================================================
rem  Parking Perks - ALWAYS-ON server app (web UI + reads ingest)
rem  Used by Task Scheduler trigger "At startup". No browser opens.
rem ============================================================
cd /d "%~dp0backend"

if not exist .venv (
  python -m venv .venv || exit /b 1
  .venv\Scripts\python -m pip install --upgrade pip -q
  .venv\Scripts\python -m pip install -r requirements.txt -q || exit /b 1
)

.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
