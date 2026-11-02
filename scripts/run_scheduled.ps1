# Плановый прогон боевого контура.
# Запускать из Планировщика заданий Windows или вручную.
# Рабочая папка должна быть корнем проекта (D:\CASE_LAB).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Не найден .venv. Сначала: python -m venv .venv и pip install -e `".[dev]`""
}

& $VenvPython -m case_lab live
exit $LASTEXITCODE
