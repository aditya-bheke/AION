# Build the Docker image used to validate AI-generated patches in isolation.
# Requires Docker Desktop running. Usage: powershell -ExecutionPolicy Bypass -File scripts\build-sandbox.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
docker build -t aion-sandbox:py310 (Join-Path $root "sandbox")
Write-Host ""
Write-Host "Built aion-sandbox:py310. Enable it in backend\.env:  AION_SANDBOX=docker"
