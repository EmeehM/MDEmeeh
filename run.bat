@echo off
rem Ejecuta MDEmeeh desde el codigo fuente en Windows. Uso: run.bat [archivo.md]
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual e instalando dependencias...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" -m emeeh_markdown %*
