# Start the local Ollama server for AION (keep this window open while using AION).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-ollama.ps1 [-OllamaDir D:\Ollama]
param([string]$OllamaDir = "D:\Ollama")

$exe = Join-Path $OllamaDir "ollama.exe"
if (-not (Test-Path $exe)) { throw "Ollama not found at $exe - run scripts\setup-ollama.ps1 first" }

$env:OLLAMA_MODELS = Join-Path $OllamaDir "models"   # model files stay on this drive
$env:OLLAMA_HOST = "127.0.0.1:11434"                  # local only
# AION's root-cause prompts are ~6-7k tokens; Ollama's default 4096 would silently cut them.
$env:OLLAMA_CONTEXT_LENGTH = "12288"

Write-Host "Ollama: models in $env:OLLAMA_MODELS, context $env:OLLAMA_CONTEXT_LENGTH tokens, http://$env:OLLAMA_HOST"
& $exe serve
