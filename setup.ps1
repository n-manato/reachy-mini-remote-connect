# One-time setup, run by setup.bat: finds (or installs) Python 3.11-3.13, creates .venv,
# installs the packages, then asks for the robot connection and tests it.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
    # The SDK needs 3.11-3.13 (64-bit); newer PCs may have 3.14 as "python".
    $candidates = @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"),
                    @("$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"))
    foreach ($c in $candidates) {
        try {
            $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
            $out = & $exe @pre -c "import sys, struct; print(sys.version_info[0], sys.version_info[1], struct.calcsize('P') * 8)" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
            $major, $minor, $bits = "$out".Trim().Split(" ")
            if ([int]$major -eq 3 -and [int]$minor -ge 11 -and [int]$minor -le 13 -and [int]$bits -eq 64) {
                return , $c
            }
        } catch { }
    }
    return $null
}

Write-Host "=== Reachy Mini starter kit setup ===" -ForegroundColor Cyan

if ($PSScriptRoot -match "OneDrive") {
    Write-Host "Warning: this folder is inside OneDrive. The Python environment (~750 MB) would be synced." -ForegroundColor Yellow
    Write-Host "         Moving the folder to e.g. C:\reachy-mini first is recommended."
    if ((Read-Host "Continue anyway? (y/N)") -notmatch "^[yY]") { exit 1 }
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.11-3.13 (64-bit) was not found." -ForegroundColor Yellow
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "Install Python 3.13 (64-bit) from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run setup.bat again."
        exit 1
    }
    if ((Read-Host "Install Python 3.13 now with winget? (Y/n)") -match "^[nN]") { exit 1 }
    winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
    $python = Find-Python
    if (-not $python) {
        Write-Host "Python was installed but not found yet. Close this window and run setup.bat again." -ForegroundColor Yellow
        exit 1
    }
}
$exe = $python[0]; $pre = @($python | Select-Object -Skip 1)
Write-Host "Using Python: $(& $exe @pre --version)"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    & $exe @pre -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv" }
}
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Write-Host "Installing packages (a few minutes the first time) ..."
& $venvPy -m pip install --disable-pip-version-check -q --upgrade pip
& $venvPy -m pip install --disable-pip-version-check -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Package installation failed (is the internet connection up?)" }

Write-Host ""
Write-Host "=== Robot connection ===" -ForegroundColor Cyan
& $venvPy -m reachy_kit.configure
exit $LASTEXITCODE
