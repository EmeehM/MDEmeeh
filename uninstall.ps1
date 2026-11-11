# Desinstala MDEmeeh (instalado con install.ps1) del usuario actual.
# Uso:  powershell -ExecutionPolicy Bypass -File .\uninstall.ps1

$ErrorActionPreference = 'SilentlyContinue'

Get-Process MDEmeeh | Stop-Process -Force
Start-Sleep -Milliseconds 500

$dest = Join-Path $env:LOCALAPPDATA 'Programs\MDEmeeh'
$cls = 'HKCU:\Software\Classes'

Remove-Item (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\MDEmeeh.lnk') -Force
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) 'MDEmeeh.lnk') -Force
Remove-Item "$cls\MDEmeeh.md" -Recurse -Force
Remove-Item "$cls\Applications\MDEmeeh.exe" -Recurse -Force
foreach ($ext in '.md', '.markdown') {
    Remove-ItemProperty -Path "$cls\$ext\OpenWithProgids" -Name 'MDEmeeh.md' -Force
}
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\MDEmeeh' -Recurse -Force

# Si este script se ejecuta desde la carpeta instalada, se borra al terminar
if ($PSScriptRoot -eq $dest) {
    Start-Process cmd.exe -ArgumentList "/c timeout /t 2 >nul & rmdir /s /q `"$dest`"" -WindowStyle Hidden
} else {
    Remove-Item $dest -Recurse -Force
}

Write-Host 'MDEmeeh desinstalado. (La configuración guardada está en HKCU\Software\Emeeh\EmeehMarkdown)'
