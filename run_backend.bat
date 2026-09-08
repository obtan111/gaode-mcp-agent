@echo off
setlocal
title Private Assistant - FastAPI Backend

REM ============================================================
REM  FastAPI backend launcher (ASCII-only to avoid codepage bugs)
REM  Usage:
REM    run_backend.bat          start dev server on port 8100
REM    run_backend.bat check    verify python/deps then exit
REM ============================================================

REM Prefer the verified Python 3.11 install; fall back to PATH python.
REM NOTE: miniconda "base" env is Python 3.7 and will NOT work
REM (typing.TypedDict requires Python 3.8+). Use this one or
REM "conda activate assistant" (Python 3.11) instead.
set "PY=C:\Users\xou\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"

if not exist ".env" (
    echo [ERROR] .env not found. Copy .env.example to .env and fill in API keys.
    pause
    exit /b 1
)

"%PY%" -c "import fastapi, uvicorn, multipart" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing web deps: fastapi uvicorn python-multipart ...
    "%PY%" -m pip install fastapi "uvicorn[standard]" python-multipart -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [ERROR] Dependency install failed. Run the pip command above manually.
        pause
        exit /b 1
    )
)

if "%~1"=="check" (
    echo [OK] Environment check passed.
    "%PY%" -c "import sys; print('Python', sys.version.split()[0], '-', sys.executable)"
    exit /b 0
)

echo Starting FastAPI backend...
echo API docs: http://127.0.0.1:8000/docs
echo Press Ctrl+C to stop.
"%PY%" -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8100
pause
