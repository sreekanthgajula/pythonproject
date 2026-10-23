@echo off
setlocal
title TradingAgents Launcher

:: Switch to script directory
set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
cd /d "%ROOT_DIR%"

echo ================================================================
echo           TradingAgents - Starting Full Stack Servers
echo ================================================================
echo.

:: 1. Check Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not found in your system PATH!
    echo Please install Python 3.10 or higher and add it to PATH.
    echo.
    pause
    exit /b 1
)

:: 2. Check npm / Node.js
where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] npm or Node.js is not found in your system PATH!
    echo Please install Node.js from https://nodejs.org
    echo.
    pause
    exit /b 1
)

:: 3. Check if frontend node_modules is installed
if not exist "%ROOT_DIR%\web\node_modules" (
    echo [SETUP] First-time setup: Installing frontend dependencies with npm install...
    cd /d "%ROOT_DIR%\web"
    call npm install
    cd /d "%ROOT_DIR%"
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to install frontend npm packages!
        pause
        exit /b 1
    )
)

:: 4. Launch Backend API (FastAPI / Uvicorn on Port 8000)
echo [1/2] Starting Backend API on http://127.0.0.1:8000 ...
start "TradingAgents - Backend API (Port 8000)" cmd /k "title TradingAgents Backend (Port 8000) && cd /d "%ROOT_DIR%" && (if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat) & (if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat) & python api/server.py"

:: 5. Launch Frontend UI (Vite on Port 3000)
echo [2/2] Starting Frontend UI on http://127.0.0.1:3000 ...
start "TradingAgents - Frontend UI (Port 3000)" cmd /k "title TradingAgents Frontend (Port 3000) && cd /d "%ROOT_DIR%\web" && npm run dev"

echo.
echo ================================================================
echo           Servers are launching in separate windows!
echo ================================================================
echo   * Backend API  : http://127.0.0.1:8000
echo   * API Docs     : http://127.0.0.1:8000/docs
echo   * Frontend UI  : http://127.0.0.1:3000
echo ================================================================
echo.
echo Opening http://localhost:3000 in your browser...
timeout /t 3 /nobreak >nul 2>&1
start http://localhost:3000

echo.
echo [INFO] You can minimize this window or close it.
echo [INFO] To stop all servers at any time, run: stop_servers.bat
echo ================================================================
echo.
pause
