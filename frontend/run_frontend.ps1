$ErrorActionPreference = "Stop"

$frontendDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $frontendDir
Write-Host "Starting frontend on http://127.0.0.1:5173" -ForegroundColor Cyan

npm run dev
