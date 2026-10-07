# DeskTidy installer: creates a private Python environment, installs DeskTidy in it, adds the `desktidy`
# command and starts the service at every sign-in. Safe to run again (it updates the installation).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'

Write-Host ''
Write-Host '  DeskTidy setup' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path $python)) {
    $check = 'import sys; print(sys.version_info >= (3, 10))'
    $base = $null
    if (Get-Command py -ErrorAction SilentlyContinue) { if ((& py -3 -c $check 2>$null) -eq 'True') { $base = 'py' } }
    if (-not $base -and (Get-Command python -ErrorAction SilentlyContinue)) {
        if ((& python -c $check 2>$null) -eq 'True') { $base = 'python' }
    }
    if (-not $base) {
        Write-Host '  [-] Python 3.10+ is required: https://www.python.org/downloads/ (tick "Add python.exe to PATH")' -ForegroundColor Red
        exit 1
    }
    Write-Host '  [*] Creating the Python environment (.venv)...'
    if ($base -eq 'py') { & py -3 -m venv $venv } else { & python -m venv $venv }
}

Write-Host '  [*] Installing DeskTidy and its libraries...'
& $python -m pip install --disable-pip-version-check -q --upgrade pip
& $python -m pip install --disable-pip-version-check -q -e "$root[ai]"
if ($LASTEXITCODE -ne 0) { Write-Host '  [-] Installation failed' -ForegroundColor Red; exit 1 }

& (Join-Path $venv 'Scripts\desktidy.exe') install
Write-Host ''
Write-Host '  Done. Open a NEW Command Prompt and type:  desktidy' -ForegroundColor Cyan
