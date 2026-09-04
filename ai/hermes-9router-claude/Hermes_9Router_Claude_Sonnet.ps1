# Hermes + 9Router + Kiro Claude Sonnet 4.5
# Simplified setup script based on the working configuration tested successfully.
#
# What this script does:
#   1. Checks the Hermes installation.
#   2. Checks that 9Router is listening on localhost:20128.
#   3. Checks that HERMES_9ROUTER_API_KEY exists in the current shell and
#      persists it to the Windows User environment if needed.
#   4. Backs up Hermes config.yaml.
#   5. Adds/updates the named 9Router provider:
#        http://localhost:20128/v1
#        kr/claude-sonnet-4.5
#   6. Preserves existing providers.
#   7. Does NOT configure a fallback provider.
#
# IMPORTANT:
#   - This script never prints API keys.
#   - It does not delete Xkiro.
#   - KAT/Nemotron is NOT made the fallback because that path was not
#     validated in the working setup.
#   - 9Router and Kiro credentials must already be configured.

$ErrorActionPreference = "Stop"

$hermesRoot = Join-Path $env:LOCALAPPDATA "hermes"
$configPath = Join-Path $hermesRoot "config.yaml"
$pythonPath = Join-Path $hermesRoot "hermes-agent\venv\Scripts\python.exe"

Write-Host "=== Hermes + 9Router Claude Sonnet 4.5 ===" -ForegroundColor Cyan
Write-Host ""

# 1) Basic checks
if (-not (Test-Path -LiteralPath $hermesRoot)) {
    throw "Hermes root not found: $hermesRoot"
}

if (-not (Test-Path -LiteralPath $configPath)) {
    throw "Hermes config not found: $configPath"
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Hermes Python not found: $pythonPath"
}

Write-Host "[1/5] Hermes installation: OK" -ForegroundColor Green

# 2) Check 9Router
$listener = Get-NetTCPConnection -LocalPort 20128 -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
    throw "9Router is not listening on port 20128. Start 9Router first."
}

Write-Host "[2/5] 9Router localhost:20128: LISTENING" -ForegroundColor Green

# 3) Check current shell API key and persist it if needed
$key = $env:HERMES_9ROUTER_API_KEY

if ([string]::IsNullOrWhiteSpace($key)) {
    throw "HERMES_9ROUTER_API_KEY is missing from the current PowerShell session."
}

$userKey = [Environment]::GetEnvironmentVariable(
    "HERMES_9ROUTER_API_KEY",
    "User"
)

if ([string]::IsNullOrWhiteSpace($userKey)) {
    [Environment]::SetEnvironmentVariable(
        "HERMES_9ROUTER_API_KEY",
        $key,
        "User"
    )
    Write-Host "[3/5] 9Router API key: persisted to User environment" -ForegroundColor Green
}
else {
    Write-Host "[3/5] 9Router API key: User environment already configured" -ForegroundColor Green
}

# 4) Backup
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = "$configPath.bak-9router-$timestamp"
Copy-Item -LiteralPath $configPath -Destination $backupPath -Force

Write-Host "[4/5] Config backup: $backupPath" -ForegroundColor Green

# 5) Update config safely through PyYAML
$helper = Join-Path $env:TEMP "hermes_set_9router_claude.py"

@'
from pathlib import Path
import sys
import yaml

config_path = Path(sys.argv[1])

with config_path.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

providers = cfg.get("providers")
if providers is None:
    providers = {}
elif not isinstance(providers, dict):
    raise SystemExit(
        "Hermes config 'providers' exists but is not a mapping; "
        "refusing to overwrite it."
    )

# Working primary provider tested successfully.
providers["9router"] = {
    "name": "9Router Claude Sonnet 4.5",
    "base_url": "http://localhost:20128/v1",
    "key_env": "HERMES_9ROUTER_API_KEY",
    "api_mode": "chat_completions",
    "model": "kr/claude-sonnet-4.5",
    "enabled": True,
}

cfg["providers"] = providers

# Primary-only configuration: do not configure a fallback provider.

with config_path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(
        cfg,
        f,
        sort_keys=False,
        allow_unicode=True,
    )

print("Primary: 9router")
print("Model: kr/claude-sonnet-4.5")
print("Endpoint: http://localhost:20128/v1")
'@ | Set-Content -LiteralPath $helper -Encoding UTF8

& $pythonPath $helper $configPath

if ($LASTEXITCODE -ne 0) {
    Copy-Item -LiteralPath $backupPath -Destination $configPath -Force
    Remove-Item -LiteralPath $helper -Force -ErrorAction SilentlyContinue
    throw "Hermes config update failed. Backup restored."
}

Remove-Item -LiteralPath $helper -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "[5/5] Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Primary:  9Router -> Kiro -> Claude Sonnet 4.5" -ForegroundColor White
Write-Host "Endpoint: http://localhost:20128/v1" -ForegroundColor White
Write-Host "Fallback: none (primary-only)" -ForegroundColor White
Write-Host ""
Write-Host "Next:" -ForegroundColor Yellow
Write-Host "  1. Open a NEW PowerShell window so User environment variables are loaded."
Write-Host "  2. Restart the Hermes gateway."
Write-Host "  3. Run: hermes model"
Write-Host "  4. Confirm: kr/claude-sonnet-4.5"
Write-Host ""
Write-Host "Backup saved at:" -ForegroundColor Yellow
Write-Host "  $backupPath"
