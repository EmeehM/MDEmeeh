"""Emeeh Markdown — editor de Markdown WYSIWYG (estilo Typora) con modo oscuro."""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPalette
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "MDEmeeh"
if getattr(sys, "frozen", False):  # ejecutable generado con PyInstaller
    STATIC_DIR = Path(sys._MEIPASS) / "emeeh_markdown" / "static"
else:
    STATIC_DIR = Path(__file__).resolve().parent / "static"
MD_FILTER = "Markdown (*.md *.markdown *.mdown *.mkd *.txt);;Todos los archivos (*)"
MD_EXTS = {".md", ".markdown", ".mdown", ".mkd", ".txt"}
MAX_RECENT = 10


# ---------------------------------------------------------------------------
# Puente JS <-> Python
# ---------------------------------------------------------------------------
class Bridge(QObject):
    dirtyChanged = Signal(bool)
    pageReady = Signal()

    @Slot(bool)
    def setDirty(self, value: bool) -> None:
        self.dirtyChanged.emit(bool(value))

    @Slot(str)
    def openUrl(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    @Slot()
    def ready(self) -> None:
        self.pageReady.emit()


class EditorPage(QWebEnginePage):
    """Intercepta navegaciones (p. ej. arrastrar un .md a la ventana)."""

    fileDropped = Signal(str)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # noqa: N802
        if not is_main_frame:
            return True
        if url.isLocalFile() and Path(url.toLocalFile()) == STATIC_DIR / "index.html":
            return True
        if url.isLocalFile():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in MD_EXTS:
                self.fileDropped.emit(path)
            return False
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return False
        return False

    def createWindow(self, _type):  # noqa: N802 - enlaces target=_blank
        return None

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        if os.environ.get("EMEEH_DEBUG"):
            print(f"[js] {source}:{line} {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Barra de búsqueda
# ---------------------------------------------------------------------------
class FindBar(QWidget):
    def __init__(self, view: QWebEngineView):
        super().__init__()
        self.view = view
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        self.input = QLineEdit(placeholderText="Buscar en el documento…")
        self.input.textChanged.connect(lambda: self.find())
        self.input.returnPressed.connect(lambda: self.find())
        prev_btn = QPushButton("↑")
        next_btn = QPushButton("↓")
        close_btn = QPushButton("✕")
        for b in (prev_btn, next_btn, close_btn):
            b.setFixedWidth(32)
        prev_btn.clicked.connect(lambda: self.find(backward=True))
        next_btn.clicked.connect(lambda: self.find())
        close_btn.clicked.connect(self.close_bar)
        lay.addWidget(self.input, 1)
        lay.addWidget(prev_btn)
        lay.addWidget(next_btn)
        lay.addWidget(close_btn)
        self.hide()

    def open_bar(self, text: str = "") -> None:
        self.show()
        if text:
            self.input.setText(text)
        self.input.setFocus()
        self.input.selectAll()

    def close_bar(self) -> None:
        self.view.page().findText("")
        self.hide()
        self.view.setFocus()

    def find(self, backward: bool = False) -> None:
        flags = QWebEnginePage.FindFlag.FindBackward if backward else QWebEnginePage.FindFlag(0)
        self.view.page().findText(self.input.text(), flags)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close_bar()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.find(backward=True)
        else:
            super().keyPressEvent(e)


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, initial_file: str | None = None):
        super().__init__()
        self.settings = QSettings("Emeeh", "EmeehMarkdown")
        self.file_path: str | None = None
        self.dirty = False
        self.page_ready = False
        self.pending_file = initial_file
        self._closing = False
        self._pdf_page: QWebEnginePage | None = None

        self.dark = self.settings.value("dark", True, type=bool)
        self.show_outline = self.settings.value("outline", True, type=bool)
        self.show_toolbar = self.settings.value("toolbar", True, type=bool)
        self.wide = self.settings.value("wide", False, type=bool)
        self.source_mode = False

        # Vista web
        self.view = QWebEngineView(self)
        self.page = EditorPage(self.view)
        self.view.setPage(self.page)
        s = self.page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
        self.page.setBackgroundColor(QColor("#1e1f22" if self.dark else "#ffffff"))
        self.page.fileDropped.connect(lambda p: self.maybe_save(lambda: self.load_file(p)))

        self.bridge = Bridge()
        self.bridge.dirtyChanged.connect(self.set_dirty)
        self.bridge.pageReady.connect(self.on_page_ready)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)

        self.find_bar = FindBar(self.view)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.find_bar)
        self.setCentralWidget(central)

        self.build_menus()
        self.apply_qt_theme()
        self.update_title()

        zoom = self.settings.value("zoom", 1.0, type=float)
        self.view.setZoomFactor(zoom)
        geom = self.settings.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        else:
            self.resize(1200, 800)

        self.view.load(QUrl.fromLocalFile(str(STATIC_DIR / "index.html")))

    # ------------------------------------------------------------------ JS
    def js(self, code: str, callback=None) -> None:
        if callback is None:
            self.page.runJavaScript(code)
        else:
            self.page.runJavaScript(code, 0, callback)

    def on_page_ready(self) -> None:
        self.page_ready = True
        self.js(f"app.setTheme({json.dumps('dark' if self.dark else 'light')})")
        self.js(f"app.toggleOutline({json.dumps(self.show_outline)})")
        self.js(f"app.toggleToolbar({json.dumps(self.show_toolbar)})")
        self.js(f"app.setFocusWidth({json.dumps(self.wide)})")
        if self.pending_file:
            path, self.pending_file = self.pending_file, None
            self.load_file(path)

    # --------------------------------------------------------------- menús
    def _action(self, menu, text, slot, shortcut=None, checkable=False, checked=False, hint=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
            act.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        elif hint:
            # Atajo gestionado por el editor web: sólo se muestra en el menú
            act.setText(f"{text}\t{hint}")
        if checkable:
            act.setCheckable(True)
            act.setChecked(checked)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def build_menus(self) -> None:
        mb = self.menuBar()

        # Archivo
        m = mb.addMenu("&Archivo")
        self._action(m, "Nuevo", lambda: self.maybe_save(self.new_file), "Ctrl+N")
        self._action(m, "Abrir…", lambda: self.maybe_save(self.open_dialog), "Ctrl+O")
        self.recent_menu = m.addMenu("Abrir reciente")
        self.rebuild_recent_menu()
        m.addSeparator()
        self._action(m, "Guardar", lambda: self.save(), "Ctrl+S")
        self._action(m, "Guardar como…", lambda: self.save(save_as=True), "Ctrl+Shift+S")
        m.addSeparator()
        self._action(m, "Exportar a HTML…", self.export_html)
        self._action(m, "Exportar a PDF…", self.export_pdf)
        m.addSeparator()
        self._action(m, "Salir", self.close, "Ctrl+Q")

        # Editar
        m = mb.addMenu("&Editar")
        self._action(m, "Deshacer", lambda: self.cmd("undo"), hint="Ctrl+Z")
        self._action(m, "Rehacer", lambda: self.cmd("redo"), hint="Ctrl+Shift+Z")
        m.addSeparator()
        self._action(m, "Buscar…", self.open_find, "Ctrl+F")
        m.addSeparator()
        self._action(m, "Limpiar formato", lambda: self.cmd("clear"))

        # Párrafo
        m = mb.addMenu("&Párrafo")
        for i in range(1, 7):
            self._action(m, f"Título {i}", lambda _=False, i=i: self.cmd(f"h{i}"), f"Ctrl+{i}")
        self._action(m, "Párrafo normal", lambda: self.cmd("paragraph"), "Ctrl+0")
        m.addSeparator()
        self._action(m, "Insertar tabla…", self.insert_table_dialog, "Ctrl+T")
        self._action(m, "Bloque de código", lambda: self.cmd("codeblock"), hint="Ctrl+Alt+C")
        self._action(m, "Cita", lambda: self.cmd("quote"), hint="Ctrl+Shift+B")
        m.addSeparator()
        self._action(m, "Lista con viñetas", lambda: self.cmd("ul"), hint="Ctrl+Shift+8")
        self._action(m, "Lista numerada", lambda: self.cmd("ol"), hint="Ctrl+Shift+7")
        self._action(m, "Lista de tareas", lambda: self.cmd("task"), hint="Ctrl+Shift+9")
        m.addSeparator()
        self._action(m, "Línea horizontal", lambda: self.cmd("hr"))

        # Formato
        m = mb.addMenu("&Formato")
        self._action(m, "Negrita", lambda: self.cmd("bold"), hint="Ctrl+B")
        self._action(m, "Cursiva", lambda: self.cmd("italic"), hint="Ctrl+I")
        self._action(m, "Subrayado", lambda: self.cmd("underline"), hint="Ctrl+U")
        self._action(m, "Tachado", lambda: self.cmd("strike"), hint="Ctrl+Shift+X")
        self._action(m, "Código en línea", lambda: self.cmd("code"), hint="Ctrl+E")
        m.addSeparator()
        self._action(m, "Enlace…", lambda: self.cmd("link"), "Ctrl+K")
        self._action(m, "Imagen…", self.insert_image)

        # Ver
        m = mb.addMenu("&Ver")
        self.act_source = self._action(m, "Modo código fuente", self.toggle_source, "Ctrl+/", checkable=True)
        m.addSeparator()
        self.act_dark = self._action(m, "Modo oscuro", self.toggle_dark, "Ctrl+Shift+D", checkable=True, checked=self.dark)
        self._action(m, "Esquema lateral", self.toggle_outline, "Ctrl+Shift+L", checkable=True, checked=self.show_outline)
        self._action(m, "Barra de formato", self.toggle_toolbar, "Ctrl+Shift+T", checkable=True, checked=self.show_toolbar)
        self._action(m, "Ancho completo", self.toggle_wide, checkable=True, checked=self.wide)
        m.addSeparator()
        self._action(m, "Acercar", lambda: self.zoom(0.1), "Ctrl+=")
        self._action(m, "Alejar", lambda: self.zoom(-0.1), "Ctrl+-")
        self._action(m, "Tamaño real", lambda: self.zoom(None), "Ctrl+Shift+0")
        m.addSeparator()
        self._action(m, "Pantalla completa", self.toggle_fullscreen, "F11")

        # Ayuda
        m = mb.addMenu("A&yuda")
        self._action(m, "Atajos y sintaxis", self.show_help, "F1")

    def flash(self, msg: str) -> None:
        self.js(f"app.flash({json.dumps(msg)})")

    def cmd(self, name: str, arg: str | None = None) -> None:
        self.js(f"app.command({json.dumps(name)}, {json.dumps(arg)})")

    # ------------------------------------------------------------ archivos
    def set_dirty(self, value: bool) -> None:
        if self.dirty != value:
            self.dirty = value
            self.update_title()

    def update_title(self) -> None:
        name = Path(self.file_path).name if self.file_path else "Sin título"
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name} — {APP_NAME}")

    def base_url(self) -> str:
        if self.file_path:
            return QUrl.fromLocalFile(str(Path(self.file_path).parent) + os.sep).toString()
        return QUrl.fromLocalFile(str(STATIC_DIR) + os.sep).toString()

    def new_file(self) -> None:
        self.file_path = None
        self.js(f"app.setContent('', {json.dumps(self.base_url())})")
        self.set_dirty(False)
        self.update_title()

    def open_dialog(self) -> None:
        start = str(Path(self.file_path).parent) if self.file_path else self.settings.value("lastDir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Abrir Markdown", start, MD_FILTER)
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        if not self.page_ready:
            self.pending_file = path
            return
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"No se pudo abrir el archivo:\n{exc}")
            self.remove_recent(path)
            return
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        text = text.replace("\r\n", "\n")
        self.file_path = str(Path(path).resolve())
        self.settings.setValue("lastDir", str(Path(self.file_path).parent))
        self.js(f"app.setContent({json.dumps(text)}, {json.dumps(self.base_url())})")
        self.set_dirty(False)
        self.update_title()
        self.add_recent(self.file_path)

    def save(self, save_as: bool = False, then=None) -> None:
        path = self.file_path
        if save_as or not path:
            start = path or str(Path(self.settings.value("lastDir", str(Path.home()))) / "documento.md")
            path, _ = QFileDialog.getSaveFileName(self, "Guardar Markdown", start, MD_FILTER)
            if not path:
                return
            if not Path(path).suffix:
                path += ".md"

        def write(md):
            if md is None:
                QMessageBox.critical(self, APP_NAME, "No se pudo obtener el contenido del editor.")
                return
            md = md.rstrip("\n") + "\n"
            try:
                Path(path).write_text(md, encoding="utf-8")
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, f"No se pudo guardar:\n{exc}")
                return
            moved = self.file_path != str(Path(path).resolve())
            self.file_path = str(Path(path).resolve())
            self.settings.setValue("lastDir", str(Path(self.file_path).parent))
            self.js("app.markSaved()")
            if moved:
                self.js(f"app.setBase({json.dumps(self.base_url())})")
            self.set_dirty(False)
            self.update_title()
            self.add_recent(self.file_path)
            self.flash(f"Guardado: {self.file_path}")
            if then:
                then()

        self.js("app.getMarkdown()", write)

    def maybe_save(self, then) -> None:
        """Si hay cambios sin guardar pregunta antes de continuar con `then`."""
        if not self.dirty:
            then()
            return
        name = Path(self.file_path).name if self.file_path else "Sin título"
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"¿Guardar los cambios de «{name}»?")
        box.setInformativeText("Si no los guardas, se perderán.")
        save_btn = box.addButton("Guardar", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton("No guardar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_btn:
            self.save(then=then)
        elif clicked is discard_btn:
            then()

    # ------------------------------------------------------------- recientes
    def recent_files(self) -> list[str]:
        val = self.settings.value("recent", [])
        if isinstance(val, str):
            val = [val]
        return [v for v in (val or []) if v]

    def add_recent(self, path: str) -> None:
        files = [p for p in self.recent_files() if p != path]
        files.insert(0, path)
        self.settings.setValue("recent", files[:MAX_RECENT])
        self.rebuild_recent_menu()

    def remove_recent(self, path: str) -> None:
        self.settings.setValue("recent", [p for p in self.recent_files() if p != path])
        self.rebuild_recent_menu()

    def rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = self.recent_files()
        if not files:
            a = self.recent_menu.addAction("(vacío)")
            a.setEnabled(False)
            return
        for p in files:
            a = self.recent_menu.addAction(p)
            a.triggered.connect(lambda _=False, p=p: self.maybe_save(lambda: self.load_file(p)))
        self.recent_menu.addSeparator()
        a = self.recent_menu.addAction("Limpiar lista")
        a.triggered.connect(lambda: (self.settings.setValue("recent", []), self.rebuild_recent_menu()))

    # ------------------------------------------------------------ inserción
    def insert_table_dialog(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Insertar tabla", "Filas x columnas (incluye encabezado):", text="3x3"
        )
        if not ok:
            return
        try:
            rows, cols = (max(1, min(100, int(x))) for x in text.lower().replace(" ", "").split("x"))
        except ValueError:
            rows, cols = 3, 3
        self.cmd("table", f"{rows}x{cols}")

    def insert_image(self) -> None:
        start = str(Path(self.file_path).parent) if self.file_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Insertar imagen", start, "Imágenes (*.png *.jpg *.jpeg *.gif *.svg *.webp *.bmp);;Todos (*)"
        )
        if not path:
            return
        if self.file_path:
            src = os.path.relpath(path, Path(self.file_path).parent).replace(os.sep, "/")
        else:
            src = QUrl.fromLocalFile(path).toString()
        src = src.replace(" ", "%20")
        self.js(f"app.insertImage({json.dumps(src)}, {json.dumps(Path(path).stem)})")

    # ------------------------------------------------------------ exportar
    def build_export_html(self, body: str, theme: str) -> str:
        css = (STATIC_DIR / "content.css").read_text(encoding="utf-8")
        title = Path(self.file_path).stem if self.file_path else "Documento"
        return f"""<!doctype html>
<html lang="es" data-theme="{theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
{css}
body {{ background: var(--bg); margin: 0; }}
.markdown-body {{ max-width: 860px; margin: 0 auto; padding: 40px 32px; }}
@media print {{ .markdown-body {{ padding: 0; max-width: none; }} pre, table, img {{ break-inside: avoid; }} }}
</style>
</head>
<body><article class="markdown-body">
{body}
</article></body>
</html>
"""

    def _export_target(self, ext: str, label: str) -> str | None:
        stem = Path(self.file_path).with_suffix(ext) if self.file_path else Path.home() / f"documento{ext}"
        path, _ = QFileDialog.getSaveFileName(self, f"Exportar a {label}", str(stem), f"{label} (*{ext})")
        if path and not path.lower().endswith(ext):
            path += ext
        return path or None

    def export_html(self) -> None:
        path = self._export_target(".html", "HTML")
        if not path:
            return

        def done(body):
            try:
                Path(path).write_text(self.build_export_html(body or "", "dark" if self.dark else "light"), encoding="utf-8")
                self.flash(f"Exportado: {path}")
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, f"No se pudo exportar:\n{exc}")

        self.js("app.getHtml()", done)

    def export_pdf(self) -> None:
        path = self._export_target(".pdf", "PDF")
        if not path:
            return

        def got_body(body):
            page = QWebEnginePage(self)
            self._pdf_page = page

            def loaded(ok):
                if not ok:
                    QMessageBox.critical(self, APP_NAME, "No se pudo generar el PDF.")
                    return
                page.printToPdf(path)

            def finished(file_path, success):
                if success:
                    self.flash(f"PDF exportado: {file_path}")
                else:
                    QMessageBox.critical(self, APP_NAME, "No se pudo escribir el PDF.")
                page.deleteLater()
                self._pdf_page = None

            page.loadFinished.connect(loaded)
            page.pdfPrintingFinished.connect(finished)
            page.setHtml(self.build_export_html(body or "", "light"), QUrl(self.base_url()))

        self.js("app.getHtml()", got_body)

    # ---------------------------------------------------------------- vista
    def toggle_source(self) -> None:
        def done(on):
            self.source_mode = bool(on)
            self.act_source.setChecked(self.source_mode)

        self.js("app.toggleSource()", done)

    def toggle_dark(self, checked: bool) -> None:
        self.dark = checked
        self.settings.setValue("dark", checked)
        self.js(f"app.setTheme({json.dumps('dark' if checked else 'light')})")
        self.page.setBackgroundColor(QColor("#1e1f22" if checked else "#ffffff"))
        self.apply_qt_theme()

    def toggle_outline(self, checked: bool) -> None:
        self.settings.setValue("outline", checked)
        self.js(f"app.toggleOutline({json.dumps(checked)})")

    def toggle_toolbar(self, checked: bool) -> None:
        self.settings.setValue("toolbar", checked)
        self.js(f"app.toggleToolbar({json.dumps(checked)})")

    def toggle_wide(self, checked: bool) -> None:
        self.settings.setValue("wide", checked)
        self.js(f"app.setFocusWidth({json.dumps(checked)})")

    def zoom(self, delta: float | None) -> None:
        z = 1.0 if delta is None else max(0.5, min(2.5, self.view.zoomFactor() + delta))
        self.view.setZoomFactor(z)
        self.settings.setValue("zoom", z)

    def toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def open_find(self) -> None:
        self.js("app.selectedText()", lambda t: self.find_bar.open_bar(t or ""))

    def apply_qt_theme(self) -> None:
        app = QApplication.instance()
        if self.dark:
            p = QPalette()
            bg, base, text = QColor("#18191c"), QColor("#1e1f22"), QColor("#d4d7dd")
            p.setColor(QPalette.ColorRole.Window, bg)
            p.setColor(QPalette.ColorRole.WindowText, text)
            p.setColor(QPalette.ColorRole.Base, base)
            p.setColor(QPalette.ColorRole.AlternateBase, bg)
            p.setColor(QPalette.ColorRole.Text, text)
            p.setColor(QPalette.ColorRole.Button, QColor("#26282c"))
            p.setColor(QPalette.ColorRole.ButtonText, text)
            p.setColor(QPalette.ColorRole.ToolTipBase, base)
            p.setColor(QPalette.ColorRole.ToolTipText, text)
            p.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6b717a"))
            p.setColor(QPalette.ColorRole.Highlight, QColor("#2f5d8f"))
            p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            p.setColor(QPalette.ColorRole.Link, QColor("#6cb6ff"))
            for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
                p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#5d636c"))
            app.setPalette(p)
        else:
            app.setPalette(app.style().standardPalette())

    # ---------------------------------------------------------------- ayuda
    def show_help(self) -> None:
        QMessageBox.information(
            self,
            "Atajos y sintaxis",
            """<h3>Escribe Markdown y se formatea al instante</h3>
<table cellspacing="4">
<tr><td><code># </code> … <code>###### </code></td><td>Títulos 1 a 6</td></tr>
<tr><td><code>**texto**</code> / <code>*texto*</code></td><td>Negrita / cursiva</td></tr>
<tr><td><code>~~texto~~</code> / <code>`código`</code></td><td>Tachado / código</td></tr>
<tr><td><code>- </code> / <code>1. </code> / <code>[ ] </code></td><td>Listas / tareas</td></tr>
<tr><td><code>&gt; </code></td><td>Cita</td></tr>
<tr><td><code>```python</code></td><td>Bloque de código</td></tr>
<tr><td><code>---</code></td><td>Línea horizontal</td></tr>
<tr><td><code>| A | B | C |</code> + Enter</td><td><b>Crea una tabla</b></td></tr>
</table>
<h3>Tablas</h3>
<p>Ctrl+T inserta una tabla. Dentro de ella: <b>Tab</b> / <b>Shift+Tab</b> para moverte
entre celdas (Tab en la última celda añade una fila). Aparece una barra
flotante para añadir/eliminar filas y columnas.</p>
<h3>Atajos</h3>
<p>Ctrl+1…6 títulos · Ctrl+0 párrafo · Ctrl+/ código fuente · Ctrl+Shift+D modo oscuro ·
Ctrl+Shift+L esquema · Ctrl+K enlace · Ctrl+clic abre enlace · Ctrl+F buscar</p>""",
        )

    # --------------------------------------------------------------- cierre
    def closeEvent(self, event):  # noqa: N802
        if self._closing or not self.dirty:
            self.settings.setValue("geometry", self.saveGeometry())
            event.accept()
            return
        event.ignore()

        def really_close():
            self._closing = True
            self.close()

        self.maybe_save(really_close)


def main() -> int:
    if sys.platform == "win32":
        # Para que Windows agrupe la ventana con su propio ícono en la barra de tareas
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Emeeh.MDEmeeh")
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Emeeh")
    app.setStyle(QStyleFactory.create("Fusion"))
    icon = QIcon()
    for name in ("icon.svg", "icon.png"):
        if (STATIC_DIR / name).exists():
            icon.addFile(str(STATIC_DIR / name))
    app.setWindowIcon(icon)

    initial = None
    for arg in sys.argv[1:]:
        if not arg.startswith("-") and Path(arg).exists():
            initial = arg
            break

    win = MainWindow(initial)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
