@echo off
chcp 65001 >nul
set PYTHONDONTWRITEBYTECODE=1
cd /d "%~dp0"

echo.
echo ============================================
echo   Job Agent - Full Stack Launcher
echo ============================================
echo.

REM ---- Dependency checks ----
python -c "import flask" 2>nul && (echo [ OK ] Flask) || (echo [WARN] Flask missing - pip install flask)
python -c "import torch" 2>nul && (echo [ OK ] PyTorch) || (echo [WARN] PyTorch missing - pip install torch)
python -c "import browser_use" 2>nul && (echo [ OK ] browser-use) || (echo [WARN] browser-use missing)
python -c "import playwright" 2>nul && (echo [ OK ] playwright) || (echo [WARN] playwright missing)
python -c "import sqlite3" 2>nul && (echo [ OK ] SQLite built-in) || (echo [ERR] SQLite missing)
echo.

REM ---- Token check ----
if "%JOB_AGENT_TOKEN%"=="" (
    echo [WARN] JOB_AGENT_TOKEN not set, using default
    set JOB_AGENT_TOKEN=job-agent-demo-token
    echo        Default token: %JOB_AGENT_TOKEN%
    echo.
)

REM ---- 1. Start Flask ----
echo [1/3] Starting Flask (localhost:5000) ...
start "JobAgent-Web" cmd /c "cd /d %cd% && python web_server.py"
timeout /t 3 >nul
echo        Web: http://127.0.0.1:5000

REM ---- 2. Start ngrok ----
echo [2/3] Starting ngrok tunnel ...
start "JobAgent-Ngrok" cmd /c "cd /d %cd% && ngrok http 5000 --log=stdout"
timeout /t 4 >nul

REM ---- 3. Get public URL ----
echo [3/3] Getting public URL ...
for /f "tokens=*" %%i in ('curl -s http://127.0.0.1:4040/api/tunnels 2^>nul ^| python -c "import sys,json; t=json.load(sys.stdin)['tunnels']; [print(t['public_url']) for t in t]" 2^>nul') do set PUBLIC_URL=%%i

echo.
echo ============================================
echo   Job Agent Ready
echo ============================================
echo   Local:  http://127.0.0.1:5000
if not "%PUBLIC_URL%"=="" (echo   Public: %PUBLIC_URL%) else (echo   Public: check JobAgent-Ngrok window)
echo   Token:  %JOB_AGENT_TOKEN%
echo.
echo   Press any key to stop all services...
echo ============================================
pause >nul

echo Stopping services...
taskkill /FI "WINDOWTITLE eq JobAgent-Web*" /T >nul 2>&1
taskkill /FI "WINDOWTITLE eq JobAgent-Ngrok*" /T >nul 2>&1
echo Done. Goodbye!
