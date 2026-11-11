# Instala MDEmeeh para el usuario actual (no requiere administrador):
#  - copia el programa a %LOCALAPPDATA%\Programs\MDEmeeh
#  - crea el acceso directo en el Menú Inicio (aparece al buscar "MDEmeeh")
#  - lo registra en "Abrir con" para archivos .md / .markdown
# Uso:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1            # instalación normal
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Desktop   # + acceso directo en el escritorio

param([switch]$Desktop)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path 'dist\MDEmeeh\MDEmeeh.exe')) {
    Write-Host 'No existe el ejecutable; generándolo...'
    & "$PSScriptRoot\build.ps1"
}

$dest = Join-Path $env:LOCALAPPDATA 'Programs\MDEmeeh'
$exe = Join-Path $dest 'MDEmeeh.exe'

Get-Process MDEmeeh -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
Copy-Item -Recurse 'dist\MDEmeeh' $dest

# Accesos directos
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $dest
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = 'Editor de Markdown con modo oscuro y tablas'
    $lnk.Save()
}
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
New-Shortcut (Join-Path $startMenu 'MDEmeeh.lnk')
if ($Desktop) { New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'MDEmeeh.lnk') }

# Asociación de archivos (por usuario, en HKCU)
function Set-Default($key, $value) {
    New-Item -Path $key -Force | Out-Null
    Set-Item -Path $key -Value $value
}
$cls = 'HKCU:\Software\Classes'
Set-Default "$cls\MDEmeeh.md" 'Documento Markdown'
Set-Default "$cls\MDEmeeh.md\DefaultIcon" "`"$exe`",0"
Set-Default "$cls\MDEmeeh.md\shell\open\command" "`"$exe`" `"%1`""
foreach ($ext in '.md', '.markdown') {
    New-Item -Path "$cls\$ext\OpenWithProgids" -Force | Out-Null
    New-ItemProperty -Path "$cls\$ext\OpenWithProgids" -Name 'MDEmeeh.md' -Value '' -PropertyType String -Force | Out-Null
}
Set-Default "$cls\Applications\MDEmeeh.exe\shell\open\command" "`"$exe`" `"%1`""
New-Item -Path "$cls\Applications\MDEmeeh.exe\SupportedTypes" -Force | Out-Null
foreach ($ext in '.md', '.markdown', '.txt') {
    New-ItemProperty -Path "$cls\Applications\MDEmeeh.exe\SupportedTypes" -Name $ext -Value '' -PropertyType String -Force | Out-Null
}

# Entrada en "Aplicaciones instaladas" para poder desinstalar desde Configuración
$uninst = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEmeeh'
New-Item -Path $uninst -Force | Out-Null
Copy-Item "$PSScriptRoot\uninstall.ps1" (Join-Path $dest 'uninstall.ps1')
$props = @{
    DisplayName     = 'MDEmeeh'
    DisplayIcon     = "$exe,0"
    Publisher       = 'Emeeh'
    DisplayVersion  = '1.0.0'
    InstallLocation = $dest
    UninstallString = "powershell.exe -ExecutionPolicy Bypass -File `"$dest\uninstall.ps1`""
}
foreach ($k in $props.Keys) { New-ItemProperty -Path $uninst -Name $k -Value $props[$k] -PropertyType String -Force | Out-Null }
New-ItemProperty -Path $uninst -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $uninst -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null

# Avisar al Explorador de que cambiaron las asociaciones
Add-Type -Namespace Win32 -Name Shell -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int e, int f, IntPtr a, IntPtr b);'
[Win32.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)

Write-Host "MDEmeeh instalado en $dest"
Write-Host 'Búscalo como "MDEmeeh" en el menú Inicio.'
Write-Host 'Para que sea la app predeterminada de .md: clic derecho en un .md > Abrir con > Elegir otra aplicación > MDEmeeh > "Siempre".'
