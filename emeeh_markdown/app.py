"""Emeeh Markdown — editor de Markdown WYSIWYG (estilo Typora) con modo oscuro."""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QUrl, Signal, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket
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
    QTabWidget,
    QToolButton,
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
# Pestaña: un documento con su propio editor web
# ---------------------------------------------------------------------------
class EditorTab(QWidget):
    stateChanged = Signal()  # cambió el título, la ruta o el estado "sin guardar"

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.settings = win.settings
        self.file_path: str | None = None
        self.dirty = False
        self.page_ready = False
        self.pending_content: str | None = None
        self.source_mode = False
        self._pdf_page: QWebEnginePage | None = None

        self.view = QWebEngineView(self)
        self.page = EditorPage(self.view)
        self.view.setPage(self.page)
        s = self.page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)
        self.page.setBackgroundColor(QColor("#1e1f22" if win.dark else "#ffffff"))
        self.page.fileDropped.connect(win.open_path)

        self.bridge = Bridge()
        self.bridge.dirtyChanged.connect(self.set_dirty)
        self.bridge.pageReady.connect(self.on_page_ready)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)

        self.find_bar = FindBar(self.view)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.find_bar)

        self.view.setZoomFactor(win.zoom_factor)
        self.view.load(QUrl.fromLocalFile(str(STATIC_DIR / "index.html")))

    # ------------------------------------------------------------------ JS
    def js(self, code: str, callback=None) -> None:
        if callback is None:
            self.page.runJavaScript(code)
        else:
            self.page.runJavaScript(code, 0, callback)

    def on_page_ready(self) -> None:
        self.page_ready = True
        w = self.win
        self.js(f"app.setTheme({json.dumps('dark' if w.dark else 'light')})")
        self.js(f"app.toggleOutline({json.dumps(w.show_outline)})")
        self.js(f"app.toggleToolbar({json.dumps(w.show_toolbar)})")
        self.js(f"app.setFocusWidth({json.dumps(w.wide)})")
        if self.pending_content is not None:
            text, self.pending_content = self.pending_content, None
            self.js(f"app.setContent({json.dumps(text)}, {json.dumps(self.base_url())})")
        if self.win.current_tab() is self:
            self.view.setFocus()

    def flash(self, msg: str) -> None:
        self.js(f"app.flash({json.dumps(msg)})")

    def cmd(self, name: str, arg: str | None = None) -> None:
        self.js(f"app.command({json.dumps(name)}, {json.dumps(arg)})")

    # ------------------------------------------------------------ estado
    @property
    def display_name(self) -> str:
        return Path(self.file_path).name if self.file_path else "Sin título"

    def is_blank(self) -> bool:
        """Pestaña nueva, sin archivo ni cambios: se puede reutilizar al abrir."""
        return self.file_path is None and not self.dirty

    def set_dirty(self, value: bool) -> None:
        if self.dirty != value:
            self.dirty = value
            self.stateChanged.emit()

    def base_url(self) -> str:
        if self.file_path:
            return QUrl.fromLocalFile(str(Path(self.file_path).parent) + os.sep).toString()
        return QUrl.fromLocalFile(str(STATIC_DIR) + os.sep).toString()

    # ------------------------------------------------------------ archivos
    def load_file(self, path: str) -> bool:
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            QMessageBox.critical(self.win, APP_NAME, f"No se pudo abrir el archivo:\n{exc}")
            self.win.remove_recent(path)
            return False
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        text = text.replace("\r\n", "\n")
        self.file_path = normalize_path(path)
        self.settings.setValue("lastDir", str(Path(self.file_path).parent))
        if self.page_ready:
            self.js(f"app.setContent({json.dumps(text)}, {json.dumps(self.base_url())})")
        else:
            self.pending_content = text
        self.dirty = False
        self.stateChanged.emit()
        self.win.add_recent(self.file_path)
        return True

    def save(self, save_as: bool = False, then=None) -> None:
        path = self.file_path
        if save_as or not path:
            start = path or str(Path(self.settings.value("lastDir", str(Path.home()))) / "documento.md")
            path, _ = QFileDialog.getSaveFileName(self.win, "Guardar Markdown", start, MD_FILTER)
            if not path:
                return
            if not Path(path).suffix:
                path += ".md"

        def write(md):
            if md is None:
                QMessageBox.critical(self.win, APP_NAME, "No se pudo obtener el contenido del editor.")
                return
            md = md.rstrip("\n") + "\n"
            try:
                Path(path).write_text(md, encoding="utf-8")
            except OSError as exc:
                QMessageBox.critical(self.win, APP_NAME, f"No se pudo guardar:\n{exc}")
                return
            new_path = normalize_path(path)
            moved = self.file_path != new_path
            self.file_path = new_path
            self.settings.setValue("lastDir", str(Path(self.file_path).parent))
            self.js("app.markSaved()")
            if moved:
                self.js(f"app.setBase({json.dumps(self.base_url())})")
            self.dirty = False
            self.stateChanged.emit()
            self.win.add_recent(self.file_path)
            self.flash(f"Guardado: {self.file_path}")
            if then:
                then()

        self.js("app.getMarkdown()", write)

    def maybe_save(self, then) -> None:
        """Si hay cambios sin guardar pregunta antes de continuar con `then`."""
        if not self.dirty:
            then()
            return
        self.win.tabs.setCurrentWidget(self)
        box = QMessageBox(self.win)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"¿Guardar los cambios de «{self.display_name}»?")
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

    # ------------------------------------------------------------ inserción
    def insert_image(self) -> None:
        start = str(Path(self.file_path).parent) if self.file_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self.win, "Insertar imagen", start, "Imágenes (*.png *.jpg *.jpeg *.gif *.svg *.webp *.bmp);;Todos (*)"
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
        path, _ = QFileDialog.getSaveFileName(self.win, f"Exportar a {label}", str(stem), f"{label} (*{ext})")
        if path and not path.lower().endswith(ext):
            path += ext
        return path or None

    def export_html(self) -> None:
        path = self._export_target(".html", "HTML")
        if not path:
            return

        def done(body):
            try:
                Path(path).write_text(
                    self.build_export_html(body or "", "dark" if self.win.dark else "light"), encoding="utf-8"
                )
                self.flash(f"Exportado: {path}")
            except OSError as exc:
                QMessageBox.critical(self.win, APP_NAME, f"No se pudo exportar:\n{exc}")

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
                    QMessageBox.critical(self.win, APP_NAME, "No se pudo generar el PDF.")
                    return
                page.printToPdf(path)

            def finished(file_path, success):
                if success:
                    self.flash(f"PDF exportado: {file_path}")
                else:
                    QMessageBox.critical(self.win, APP_NAME, "No se pudo escribir el PDF.")
                page.deleteLater()
                self._pdf_page = None

            page.loadFinished.connect(loaded)
            page.pdfPrintingFinished.connect(finished)
            page.setHtml(self.build_export_html(body or "", "light"), QUrl(self.base_url()))

        self.js("app.getHtml()", got_body)

    # ---------------------------------------------------------------- vista
    def set_theme(self, dark: bool) -> None:
        self.js(f"app.setTheme({json.dumps('dark' if dark else 'light')})")
        self.page.setBackgroundColor(QColor("#1e1f22" if dark else "#ffffff"))

    def open_find(self) -> None:
        self.js("app.selectedText()", lambda t: self.find_bar.open_bar(t or ""))


def normalize_path(path: str) -> str:
    """Ruta absoluta canónica, para detectar si un archivo ya está abierto."""
    return str(Path(path).resolve())


def same_path(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(a) == os.path.normcase(b)


# ---------------------------------------------------------------------------
# Ventana principal (contiene las pestañas)
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, initial_files: list[str] | None = None):
        super().__init__()
        self.settings = QSettings("Emeeh", "EmeehMarkdown")
        self._closing = False

        self.dark = self.settings.value("dark", True, type=bool)
        self.show_outline = self.settings.value("outline", True, type=bool)
        self.show_toolbar = self.settings.value("toolbar", True, type=bool)
        self.wide = self.settings.value("wide", False, type=bool)
        self.zoom_factor = self.settings.value("zoom", 1.0, type=float)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.tabCloseRequested.connect(lambda i: self.close_tab(self.tabs.widget(i)))
        self.tabs.currentChanged.connect(self.on_current_changed)
        new_btn = QToolButton(self.tabs)
        new_btn.setText("+")
        new_btn.setToolTip("Nueva pestaña (Ctrl+N)")
        new_btn.setAutoRaise(True)
        new_btn.clicked.connect(self.new_tab)
        self.tabs.setCornerWidget(new_btn, Qt.Corner.TopRightCorner)
        self.setCentralWidget(self.tabs)

        self.build_menus()
        self.apply_qt_theme()

        geom = self.settings.value("geometry")
        if geom is not None:
            self.restoreGeometry(geom)
        else:
            self.resize(1200, 800)

        self.new_tab()
        self.open_paths(initial_files or [], activate=False)

    # ------------------------------------------------------------- pestañas
    def current_tab(self) -> EditorTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, EditorTab) else None

    def all_tabs(self) -> list[EditorTab]:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def new_tab(self) -> EditorTab:
        tab = EditorTab(self)
        tab.stateChanged.connect(lambda t=tab: self.update_tab_label(t))
        idx = self.tabs.addTab(tab, tab.display_name)
        self.tabs.setCurrentIndex(idx)
        self.update_tab_label(tab)
        return tab

    def find_tab(self, path: str) -> EditorTab | None:
        for tab in self.all_tabs():
            if same_path(tab.file_path, path):
                return tab
        return None

    def open_path(self, path: str) -> None:
        """Abre `path`: si ya está abierto lo muestra; si no, en una pestaña nueva."""
        path = normalize_path(path)
        existing = self.find_tab(path)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
            return
        cur = self.current_tab()
        tab = cur if cur is not None and cur.is_blank() else self.new_tab()
        self.tabs.setCurrentWidget(tab)
        if not tab.load_file(path) and tab is not cur and tab.is_blank() and self.tabs.count() > 1:
            self._remove_tab(tab)

    def open_paths(self, paths: list[str], activate: bool = True) -> None:
        for p in paths:
            self.open_path(p)
        if activate:
            self.bring_to_front()

    def close_tab(self, tab: EditorTab | None) -> None:
        if tab is not None:
            tab.maybe_save(lambda: self._remove_tab(tab))

    def _remove_tab(self, tab: EditorTab) -> None:
        idx = self.tabs.indexOf(tab)
        if idx < 0:
            return
        self.tabs.removeTab(idx)
        tab.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab()

    def cycle_tab(self, step: int) -> None:
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % n)

    def update_tab_label(self, tab: EditorTab) -> None:
        idx = self.tabs.indexOf(tab)
        if idx < 0:
            return
        self.tabs.setTabText(idx, f"{'• ' if tab.dirty else ''}{tab.display_name}")
        self.tabs.setTabToolTip(idx, tab.file_path or "Sin título")
        if tab is self.current_tab():
            self.update_title()

    def on_current_changed(self, _idx: int) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        self.act_source.setChecked(tab.source_mode)
        self.update_title()
        tab.view.setFocus()

    def update_title(self) -> None:
        tab = self.current_tab()
        name = tab.display_name if tab else "Sin título"
        dirty = bool(tab and tab.dirty)
        self.setWindowTitle(f"{'• ' if dirty else ''}{name} — {APP_NAME}")

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    # --------------------------------------------------------------- menús
    def _action(self, menu, text, slot, shortcut=None, checkable=False, checked=False, hint=None):
        act = QAction(text, self)
        if shortcut:
            shortcuts = shortcut if isinstance(shortcut, list) else [shortcut]
            act.setShortcuts([QKeySequence(s) for s in shortcuts])
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

    def _on_tab(self, method: str, *args):
        """Crea un slot que llama a `method` en la pestaña actual."""

        def run(*_):
            tab = self.current_tab()
            if tab is not None:
                getattr(tab, method)(*args)

        return run

    def cmd(self, name: str, arg: str | None = None) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.cmd(name, arg)

    def build_menus(self) -> None:
        mb = self.menuBar()

        # Archivo
        m = mb.addMenu("&Archivo")
        self._action(m, "Nueva pestaña", self.new_tab, "Ctrl+N")
        self._action(m, "Abrir…", self.open_dialog, "Ctrl+O")
        self.recent_menu = m.addMenu("Abrir reciente")
        self.rebuild_recent_menu()
        m.addSeparator()
        self._action(m, "Guardar", lambda: self._on_tab("save")(), "Ctrl+S")
        self._action(m, "Guardar como…", lambda: self._on_tab("save", True)(), "Ctrl+Shift+S")
        m.addSeparator()
        self._action(m, "Exportar a HTML…", self._on_tab("export_html"))
        self._action(m, "Exportar a PDF…", self._on_tab("export_pdf"))
        m.addSeparator()
        self._action(m, "Cerrar pestaña", lambda: self.close_tab(self.current_tab()), "Ctrl+W")
        self._action(m, "Salir", self.close, "Ctrl+Q")

        # Editar
        m = mb.addMenu("&Editar")
        self._action(m, "Deshacer", lambda: self.cmd("undo"), hint="Ctrl+Z")
        self._action(m, "Rehacer", lambda: self.cmd("redo"), hint="Ctrl+Shift+Z")
        m.addSeparator()
        self._action(m, "Buscar…", self._on_tab("open_find"), "Ctrl+F")
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
        self._action(m, "Imagen…", self._on_tab("insert_image"))

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
        self._action(m, "Pestaña siguiente", lambda: self.cycle_tab(1), ["Ctrl+Tab", "Ctrl+PgDown"])
        self._action(m, "Pestaña anterior", lambda: self.cycle_tab(-1), ["Ctrl+Shift+Tab", "Ctrl+PgUp"])
        m.addSeparator()
        self._action(m, "Pantalla completa", self.toggle_fullscreen, "F11")

        # Ayuda
        m = mb.addMenu("A&yuda")
        self._action(m, "Atajos y sintaxis", self.show_help, "F1")

    # ------------------------------------------------------------ archivos
    def open_dialog(self) -> None:
        tab = self.current_tab()
        if tab and tab.file_path:
            start = str(Path(tab.file_path).parent)
        else:
            start = self.settings.value("lastDir", str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(self, "Abrir Markdown", start, MD_FILTER)
        for p in paths:
            self.open_path(p)

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
            a.triggered.connect(lambda _=False, p=p: self.open_path(p))
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

    # ---------------------------------------------------------------- vista
    def toggle_source(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return

        def done(on):
            tab.source_mode = bool(on)
            if tab is self.current_tab():
                self.act_source.setChecked(tab.source_mode)

        tab.js("app.toggleSource()", done)

    def toggle_dark(self, checked: bool) -> None:
        self.dark = checked
        self.settings.setValue("dark", checked)
        for tab in self.all_tabs():
            tab.set_theme(checked)
        self.apply_qt_theme()

    def toggle_outline(self, checked: bool) -> None:
        self.show_outline = checked
        self.settings.setValue("outline", checked)
        for tab in self.all_tabs():
            tab.js(f"app.toggleOutline({json.dumps(checked)})")

    def toggle_toolbar(self, checked: bool) -> None:
        self.show_toolbar = checked
        self.settings.setValue("toolbar", checked)
        for tab in self.all_tabs():
            tab.js(f"app.toggleToolbar({json.dumps(checked)})")

    def toggle_wide(self, checked: bool) -> None:
        self.wide = checked
        self.settings.setValue("wide", checked)
        for tab in self.all_tabs():
            tab.js(f"app.setFocusWidth({json.dumps(checked)})")

    def zoom(self, delta: float | None) -> None:
        self.zoom_factor = 1.0 if delta is None else max(0.5, min(2.5, self.zoom_factor + delta))
        for tab in self.all_tabs():
            tab.view.setZoomFactor(self.zoom_factor)
        self.settings.setValue("zoom", self.zoom_factor)

    def toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

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
<h3>Pestañas</h3>
<p>Cada archivo se abre en una pestaña de la misma ventana. Si el archivo ya está
abierto, se muestra su pestaña. Ctrl+N nueva · Ctrl+W cerrar ·
Ctrl+Tab / Ctrl+Shift+Tab cambiar de pestaña.</p>
<h3>Atajos</h3>
<p>Ctrl+1…6 títulos · Ctrl+0 párrafo · Ctrl+/ código fuente · Ctrl+Shift+D modo oscuro ·
Ctrl+Shift+L esquema · Ctrl+K enlace · Ctrl+clic abre enlace · Ctrl+F buscar</p>""",
        )

    # --------------------------------------------------------------- cierre
    def closeEvent(self, event):  # noqa: N802
        dirty = [t for t in self.all_tabs() if t.dirty]
        if self._closing or not dirty:
            self.settings.setValue("geometry", self.saveGeometry())
            event.accept()
            return
        event.ignore()
        self._close_chain(dirty)

    def _close_chain(self, pending: list[EditorTab]) -> None:
        """Pregunta por cada pestaña con cambios; si se cancela alguna, no se cierra."""
        if not pending:
            self._closing = True
            self.close()
            return
        pending[0].maybe_save(lambda: self._close_chain(pending[1:]))


# ---------------------------------------------------------------------------
# Instancia única: un segundo arranque pasa sus archivos a la ventana existente
# ---------------------------------------------------------------------------
def server_name() -> str:
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return f"MDEmeeh-{''.join(c for c in user if c.isalnum())}"


def send_to_running_instance(paths: list[str]) -> bool:
    """Envía `paths` a una instancia abierta. Devuelve True si había una."""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(500):
        return False
    if sys.platform == "win32":
        # Permite que la instancia existente pase al primer plano
        try:
            import ctypes

            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except (AttributeError, OSError):
            pass
    sock.write((json.dumps(paths) + "\n").encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(1000)
    return True


class InstanceServer(QObject):
    filesReceived = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(server_name()):
            # Socket huérfano de una ejecución anterior que terminó mal
            QLocalServer.removeServer(server_name())
            self.server.listen(server_name())
        self.server.newConnection.connect(self._on_connection)

    def _on_connection(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            buf = bytearray()

            def read(sock=sock, buf=buf):
                buf.extend(bytes(sock.readAll()))
                if b"\n" in buf:
                    line = bytes(buf).split(b"\n", 1)[0]
                    buf.clear()
                    try:
                        paths = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        paths = []
                    self.filesReceived.emit([p for p in paths if isinstance(p, str)])

            sock.readyRead.connect(read)
            sock.disconnected.connect(sock.deleteLater)


def main() -> int:
    if sys.platform == "win32":
        # Para que Windows agrupe la ventana con su propio ícono en la barra de tareas
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Emeeh.MDEmeeh")
        except (AttributeError, OSError):
            pass

    initial = [normalize_path(a) for a in sys.argv[1:] if not a.startswith("-") and Path(a).is_file()]

    app = QApplication(sys.argv)
    if send_to_running_instance(initial):
        return 0

    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Emeeh")
    app.setStyle(QStyleFactory.create("Fusion"))
    icon = QIcon()
    for name in ("icon.svg", "icon.png"):
        if (STATIC_DIR / name).exists():
            icon.addFile(str(STATIC_DIR / name))
    app.setWindowIcon(icon)

    win = MainWindow(initial)
    server = InstanceServer(app)
    server.filesReceived.connect(win.open_paths)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
