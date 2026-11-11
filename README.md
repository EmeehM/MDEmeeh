# MDEmeeh

Editor de Markdown de escritorio, simple y con **modo oscuro**, que formatea el texto
mientras escribes (estilo Typora): escribe `# ` y la línea se convierte en un título,
`**texto**` en negrita, `| A | B |` + Enter en una tabla…

Funciona en **Linux** y **Windows**.

## Funciones

- Edición WYSIWYG: títulos, negrita, cursiva, tachado, código, enlaces, citas,
  listas, listas de tareas, bloques de código con resaltado, líneas, imágenes.
- **Tablas**: `Ctrl+T` o escribe `| Col1 | Col2 |` y pulsa Enter. `Tab`/`Shift+Tab`
  navega entre celdas; barra flotante para añadir/quitar filas y columnas.
- Modo código fuente (`Ctrl+/`) para ver/editar el Markdown crudo.
- Modo oscuro / claro (`Ctrl+Shift+D`), esquema lateral (`Ctrl+Shift+L`),
  buscar (`Ctrl+F`), zoom, pantalla completa (`F11`), archivos recientes.
- Exportar a HTML y PDF. Abrir archivos arrastrándolos a la ventana.
- Aviso de cambios sin guardar. El Markdown guardado es limpio y estándar (GFM).

Ver todos los atajos en **Ayuda → Atajos y sintaxis** (`F1`).

## Linux

```bash
./build.sh               # genera el ejecutable en dist/MDEmeeh/MDEmeeh
./install-desktop.sh     # lo copia a ~/.local/opt/MDEmeeh y lo agrega al menú de apps
```

Tras instalar, búscalo como **MDEmeeh** en el buscador de aplicaciones o ejecuta
`mdemeeh archivo.md`. El ejecutable incluye todo (Python, Qt y `libxcb-cursor`).

Ejecutar desde el código sin compilar: `./run.sh [archivo.md]`
(requiere `sudo apt install libxcb-cursor0`).

## Windows

Requisito: [Python 3.10+](https://www.python.org/downloads/) (marcar *Add python.exe to PATH*).

En PowerShell, dentro de la carpeta del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1     # genera dist\MDEmeeh\MDEmeeh.exe
powershell -ExecutionPolicy Bypass -File .\install.ps1   # instala (agrega -Desktop para acceso en el escritorio)
```

`install.ps1` (no requiere administrador):

- copia el programa a `%LOCALAPPDATA%\Programs\MDEmeeh`,
- crea el acceso en el **Menú Inicio** (búscalo como *MDEmeeh*),
- lo agrega a **Abrir con** para `.md` y `.markdown`,
- lo registra en *Configuración → Aplicaciones* para poder desinstalarlo.

Para hacerlo la app predeterminada de `.md`: clic derecho en un `.md` →
*Abrir con* → *Elegir otra aplicación* → **MDEmeeh** → *Siempre*.

Desinstalar: `powershell -ExecutionPolicy Bypass -File .\uninstall.ps1`
o desde *Configuración → Aplicaciones*.

Ejecutar desde el código sin compilar: `run.bat [archivo.md]`.

## Estructura

```
emeeh_markdown/app.py       Ventana Qt (PySide6 + QtWebEngine), archivos, menús
emeeh_markdown/static/      Interfaz web: index.html, CSS, iconos y bundle.js compilado
web/src/main.js             Fuente del editor (Tiptap + tiptap-markdown)
packaging/                  Spec de PyInstaller, lanzador e icono .ico
build.sh / build.ps1        Generan el ejecutable (Linux / Windows)
install-desktop.sh          Instalación en Linux
install.ps1 / uninstall.ps1 Instalación / desinstalación en Windows
```

## Modificar el editor web

`bundle.js` ya viene compilado en el repositorio, así que Node.js sólo hace falta
si cambias `web/src/main.js`:

```bash
cd web && npm install && npm run build   # regenera emeeh_markdown/static/bundle.js
```

Para regenerar los iconos tras cambiar `icon.svg`: `python packaging/make_icons.py`.
