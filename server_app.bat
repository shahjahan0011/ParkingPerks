@echo off
rem ============================================================
rem  Parking Perks - ALWAYS-ON server app (web UI + reads ingest)
rem  Used by Task Scheduler trigger "At startup".
rem  Everything is also written to backend\data\server_app.log
rem ============================================================
setlocal
cd /d "%~dp0backend"
if not exist data mkdir data
set LOG=data\server_app.log

echo ============================================== >> "%LOG%"
echo [%date% %time%] server_app.bat starting >> "%LOG%"

where python >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Python was not found on PATH. >> "%LOG%"
  echo Python was not found on PATH for this user.
  echo If "python --version" works in YOUR command prompt but this fails,
  echo Python was installed per-user and the SYSTEM account can't see it.
  pause
  exit /b 1
)

rem A venv copied from another computer has hard-coded paths and is dead.
rem If it can't even run "import sys", wipe it and rebuild.
if exist .venv (
  .venv\Scripts\python -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo [%date% %time%] .venv is broken or copied from another machine - rebuilding >> "%LOG%"
    echo The existing environment is broken ^(probably copied from another
    echo computer^). Rebuilding it now - takes a few minutes...
    rmdir /s /q .venv
  )
)

if not exist .venv (
  echo [%date% %time%] creating venv... >> "%LOG%"
  echo First-time setup: creating environment and installing packages.
  echo This takes a few minutes. Progress is logged to backend\data\server_app.log
  python -m venv .venv >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo venv creation FAILED - see backend\data\server_app.log
    pause
    exit /b 1
  )
  .venv\Scripts\python -m pip install --upgrade pip >> "%LOG%" 2>&1
  .venv\Scripts\python -m pip install -r requirements.txt >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo Package install FAILED - usually no internet access or a proxy.
    echo See backend\data\server_app.log for the real error.
    pause
    exit /b 1
  )
  echo [%date% %time%] setup complete >> "%LOG%"
)

echo [%date% %time%] starting uvicorn on 127.0.0.1:8000 >> "%LOG%"
echo Parking Perks server starting on http://127.0.0.1:8000 - keep this window open.
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info >> "%LOG%" 2>&1

echo [%date% %time%] uvicorn EXITED with errorlevel %errorlevel% >> "%LOG%"
echo.
echo The server stopped. Last lines of the log:
echo ------------------------------------------
powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 25"
pause
