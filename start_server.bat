@echo off
setlocal

:: Set the project root to the directory containing this script
set "PROJECT_ROOT=%~dp0"
:: Remove trailing backslash
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

:: Define the venv Python executable
set "PYTHON_EXE=%PROJECT_ROOT%\venv\Scripts\python.exe"

:: Ensure the executable exists
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment Python not found at: %PYTHON_EXE%
    echo Please ensure the venv is correctly created.
    exit /b 1
)

:: Clear PYTHONPATH to prevent global site-packages from loading
set PYTHONPATH=
:: Do NOT set PYTHONHOME in venv environments
set PYTHONHOME=

echo [INFO] Starting VoiceGuard server using isolated venv Python:
echo %PYTHON_EXE%
echo.

"%PYTHON_EXE%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
