<#
.SYNOPSIS
  EAP-5 watchdog setup and launcher for Windows (PowerShell 5.1+). Idempotent; offline at runtime.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File EAP_5_Watchdog/scripts/setup_watchdog.ps1 -Action validate
  ... -Action check | validate | run | start | status | stop   [-Python C:\path\python.exe] [-Config path] [-Install]
#>
param(
    [ValidateSet('check', 'validate', 'run', 'start', 'status', 'stop')][string]$Action = 'validate',
    [string]$Python = '',
    [string]$Config = '',
    [switch]$Install,
    [switch]$AllowGlobalInstall
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Fail([string]$Message, [string]$Hint) {
    Write-Host "SETUP FAILED: $Message" -ForegroundColor Red
    if ($Hint) { Write-Host "  Fix: $Hint" }
    exit 1
}

if ($env:OS -ne 'Windows_NT') { Fail 'this script targets Windows' 'use EAP_5_Watchdog/scripts/setup_watchdog.sh on Linux' }

# 1. Interpreter: explicit > active venv > python on PATH. Never creates or modifies a global environment.
if (-not $Python) {
    if ($env:VIRTUAL_ENV -and (Test-Path (Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'))) {
        $Python = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
    } else {
        $found = Get-Command python -ErrorAction SilentlyContinue
        if ($found) { $Python = $found.Source }
    }
}
if (-not $Python -or -not (Test-Path $Python)) { Fail 'no Python interpreter found' 'pass -Python C:\path\to\python.exe' }
$version = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$version -lt [version]'3.11') { Fail "Python $version is too old" 'use Python 3.11 or newer' }
$inVenv = (& $Python -c "import sys; print(sys.prefix != sys.base_prefix)") -eq 'True'
Write-Host "Python: $Python ($version, venv=$inVenv)"

# 2. Watchdog dependencies. Install only on request, never silently into a global interpreter.
& $Python -c "import pydantic, psutil" 2>$null
if ($LASTEXITCODE -ne 0) {
    if (-not $Install) { Fail 'watchdog dependencies missing (pydantic, psutil)' 'rerun with -Install inside a virtual environment' }
    if (-not $inVenv -and -not $AllowGlobalInstall) { Fail 'refusing to install into a non-virtual-environment interpreter' 'activate a venv, or add -AllowGlobalInstall' }
    & $Python -m pip install -r (Join-Path $root 'EAP_5_Watchdog\requirements.txt')
    if ($LASTEXITCODE -ne 0) { Fail 'pip install failed' 'check the requirements file and local package index' }
}
Write-Host 'Watchdog dependencies: OK'

# 3. Service dependencies are reported, not installed (they belong to the services' own requirements).
& $Python -c "import uvicorn, fastapi, ultralytics" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host 'WARNING: backend dependencies missing in this interpreter (see requirements.txt)' -ForegroundColor Yellow }
& $Python -c "import streamlit" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host 'WARNING: dashboard dependencies missing in this interpreter (see Frontend/requirements.txt)' -ForegroundColor Yellow }
if ($Action -eq 'check') { Write-Host 'CHECK OK'; exit 0 }

# 4. Validate configuration (executables, working directories, local model file + checksum; no downloads).
$configArgs = @()
if ($Config) { $configArgs = @('--config', $Config) }
Push-Location $root
try {
    & $Python -m EAP_5_Watchdog validate @configArgs
    if ($LASTEXITCODE -ne 0) { Fail 'configuration validation failed' 'see PROBLEM lines above' }
    if ($Action -eq 'validate') { exit 0 }
    & $Python -m EAP_5_Watchdog $Action @configArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
