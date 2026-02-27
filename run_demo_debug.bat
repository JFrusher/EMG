@echo off
setlocal
cd /d "%~dp0"

set "PY="

if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" -V >nul 2>nul
  if not errorlevel 1 set "PY=venv\Scripts\python.exe"
)
if not defined PY if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" (
  "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" -V >nul 2>nul
  if not errorlevel 1 set "PY=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
)
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
  "%LocalAppData%\Programs\Python\Python312\python.exe" -V >nul 2>nul
  if not errorlevel 1 set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not defined PY if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
  "%LocalAppData%\Programs\Python\Python311\python.exe" -V >nul 2>nul
  if not errorlevel 1 set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
)
if not defined PY if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
  "%LocalAppData%\Programs\Python\Python310\python.exe" -V >nul 2>nul
  if not errorlevel 1 set "PY=%LocalAppData%\Programs\Python\Python310\python.exe"
)
if not defined PY (
  py -3 -V >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python -V >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo Could not find a working Python interpreter.
  echo Install Python 3.10+ or create venv\Scripts\python.exe, then retry.
  pause
  exit /b 1
)

echo Using Python: %PY%

echo Starting EMG debug console demo (dataset emulation, loop)...
if "%~1"=="" (
  %PY% public_engagement_demo.py --source dataset --dataset-source raw --replay-speed 1.0 --replay-loop --ui-mode debug
) else (
  %PY% public_engagement_demo.py %*
)
if errorlevel 1 (
  echo.
  echo Debug demo exited with an error.
  pause
)
