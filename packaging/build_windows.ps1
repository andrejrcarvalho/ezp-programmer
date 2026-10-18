# Build dist\EZP-Programmer-<version>-windows-x64.exe
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

uv sync --locked --group build
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
$version = (uv run python -c "import ezp_programmer; print(ezp_programmer.__version__)").Trim()

# Absolute paths: PyInstaller resolves relative ones from --specpath.
$root = (Get-Location).Path
uv run pyinstaller --noconfirm --clean --onefile --windowed `
    --name ezp-programmer `
    --icon "$root\src\ezp_programmer\assets\ezp-programmer.ico" `
    --collect-data ezp_programmer `
    --collect-all libusb_package `
    --paths "$root\src" `
    --distpath build\dist-windows --workpath build\work-windows --specpath build `
    "$root\src\ezp_programmer\__main__.py"
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

# The windowed exe has no console, so wait for it explicitly and check the exit code.
$check = Start-Process -FilePath build\dist-windows\ezp-programmer.exe -ArgumentList "--self-check" -Wait -PassThru
if ($check.ExitCode -ne 0) { throw "self-check of the built exe failed ($($check.ExitCode))" }

New-Item -ItemType Directory -Force dist | Out-Null
$out = "dist\EZP-Programmer-$version-windows-x64.exe"
Copy-Item build\dist-windows\ezp-programmer.exe $out -Force
Write-Host "Built $out"
