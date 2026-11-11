"""Genera packaging/icon.ico (Windows) y static/icon.png a partir de static/icon.svg.

Uso:  python packaging/make_icons.py
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "emeeh_markdown" / "static" / "icon.svg"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(renderer: QSvgRenderer, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def main() -> None:
    QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(SVG))
    pngs = [png_bytes(render(renderer, s)) for s in SIZES]

    # ICO con imágenes PNG embebidas (válido desde Windows Vista)
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries, blobs = b"", b""
    for size, data in zip(SIZES, pngs):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    (ROOT / "packaging" / "icon.ico").write_bytes(header + entries + blobs)
    (ROOT / "emeeh_markdown" / "static" / "icon.png").write_bytes(pngs[-1])
    print("Iconos generados.")


if __name__ == "__main__":
    main()
