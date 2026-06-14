$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Virtual environment not found. Creating .venv..."
    python -m venv (Join-Path $ProjectRoot ".venv")
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e $ProjectRoot
& $Python -m pip install pyinstaller

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name AssetForge `
        --paths src `
        --add-data "src\assetforge\gui\web;assetforge\gui\web" `
        --add-data "src\assetforge\blender\scripts;assetforge\blender\scripts" `
        src\assetforge\app\main.py
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Build complete:"
Write-Host (Join-Path $ProjectRoot "dist\AssetForge\AssetForge.exe")
