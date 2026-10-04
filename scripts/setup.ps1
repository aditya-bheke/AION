# One-time setup for AION on Windows (PowerShell).
# Usage (from the repository root):  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> Creating Python virtual environment (backend\.venv)"
if (-not (Test-Path "backend\.venv")) { python -m venv backend\.venv }
& backend\.venv\Scripts\python -m pip install --upgrade pip | Out-Null
& backend\.venv\Scripts\python -m pip install -r backend\requirements.txt

Write-Host "==> Installing and building the dashboard (frontend\dist)"
Push-Location frontend
npm install --no-fund --no-audit
npm run build
Pop-Location

if (-not (Test-Path "backend\.env")) {
    Copy-Item backend\.env.example backend\.env
    Write-Host "==> Created backend\.env (edit it to configure an LLM provider)"
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  Terminal 1:  cd backend; .venv\Scripts\python -m aion        (then open http://127.0.0.1:8000)"
Write-Host "  Terminal 2:  backend\.venv\Scripts\python demo\run_demo.py --fresh"
