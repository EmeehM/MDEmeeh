# Genera el ejecutable de Windows: dist\MDEmeeh\MDEmeeh.exe
# Uso (PowerShell, en la carpeta del proyecto):
#   powershell -ExecutionPolicy Bypass -File .\build.ps1

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'Creando entorno virtual...'
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { python -m venv .venv }
    else { throw 'No se encontró Python. Instálalo desde https://www.python.org (marca "Add to PATH").' }
}

Write-Host 'Instalando dependencias...'
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación de dependencias.' }

if (-not (Test-Path 'packaging\icon.ico')) { & $py packaging\make_icons.py }

Write-Host 'Generando ejecutable...'
& $py -m PyInstaller packaging\MDEmeeh.spec --noconfirm --distpath dist --workpath build --log-level WARN
if ($LASTEXITCODE -ne 0) { throw 'Falló PyInstaller.' }

# Poda de recursos que la app no usa
$qt = 'dist\MDEmeeh\_internal\PySide6'
if (Test-Path "$qt\qml") { Remove-Item -Recurse -Force "$qt\qml" }
if (Test-Path "$qt\translations") {
    Get-ChildItem "$qt\translations" -Filter *.qm |
        Where-Object { $_.Name -notmatch '_(es|en)\.qm$' } | Remove-Item -Force
}
if (Test-Path "$qt\translations\qtwebengine_locales") {
    Get-ChildItem "$qt\translations\qtwebengine_locales" -Filter *.pak |
        Where-Object { $_.Name -notmatch '^(es.*|en-US)\.pak$' } | Remove-Item -Force
}

$size = (Get-ChildItem dist\MDEmeeh -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Listo: dist\MDEmeeh\MDEmeeh.exe  ({0:N0} MB)" -f $size)
Write-Host 'Para instalarlo:  powershell -ExecutionPolicy Bypass -File .\install.ps1'
