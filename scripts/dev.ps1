# Starts the Gatekeeper worker and dashboard, each in its own PowerShell window.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$root = Split-Path -Parent $PSScriptRoot

Start-Process powershell -WorkingDirectory $root -ArgumentList '-NoExit', '-Command', 'uv run python -m worker'
Start-Process powershell -WorkingDirectory $root -ArgumentList '-NoExit', '-Command', 'uv run streamlit run app/Home.py'

Write-Host "Gatekeeper starting: dashboard at http://127.0.0.1:8501"
