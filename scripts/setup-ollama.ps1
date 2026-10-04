# One-time: install portable Ollama (no installer, nothing on C:) and download AION's local model.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup-ollama.ps1 [-OllamaDir D:\Ollama] [-Model qwen2.5-coder:7b]
param([string]$OllamaDir = "D:\Ollama", [string]$Model = "qwen2.5-coder:7b")
$ErrorActionPreference = "Stop"

$exe = Join-Path $OllamaDir "ollama.exe"
if (-not (Test-Path $exe)) {
    New-Item -ItemType Directory -Force (Join-Path $OllamaDir "models") | Out-Null
    $zip = Join-Path $OllamaDir "ollama-windows-amd64.zip"
    Write-Host "==> Downloading Ollama (~1.4 GB) to $OllamaDir"
    curl.exe -L --fail -o $zip https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip
    Expand-Archive -Path $zip -DestinationPath $OllamaDir -Force
    Remove-Item $zip
}
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", (Join-Path $OllamaDir "models"), "User")

Write-Host "==> Starting a temporary Ollama server to download $Model (~4.7 GB)"
$env:OLLAMA_MODELS = Join-Path $OllamaDir "models"
$env:OLLAMA_HOST = "127.0.0.1:11434"
$server = Start-Process -FilePath $exe -ArgumentList "serve" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 5
& $exe pull $Model
Stop-Process -Id $server.Id -Force

Write-Host ""
Write-Host "Done. Add to backend\.env:"
Write-Host "  AION_OPENAI_BASE_URL=http://127.0.0.1:11434/v1"
Write-Host "  AION_OPENAI_MODEL=$Model"
Write-Host "Then start the model server with: scripts\start-ollama.ps1"
