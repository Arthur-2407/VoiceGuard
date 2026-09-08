$ErrorActionPreference = "Stop"

# Get the directory of this script
$ProjectRoot = $PSScriptRoot

# Define the venv Python executable
$PythonExe = Join-Path $ProjectRoot "venv\Scripts\python.exe"

if (-Not (Test-Path $PythonExe)) {
    Write-Error "[ERROR] Virtual environment Python not found at: $PythonExe"
    exit 1
}

# Clear environment variables that might cause global Python bleeding
$env:PYTHONPATH = ""
$env:PYTHONHOME = ""

Write-Host "[INFO] Starting VoiceGuard server using isolated venv Python:" -ForegroundColor Cyan
Write-Host $PythonExe -ForegroundColor Green
Write-Host ""

& $PythonExe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
