#!/usr/bin/env bash
# Genera el ejecutable dist/MDEmeeh/MDEmeeh e instala la app (ver install-desktop.sh)
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt pyinstaller

# libxcb-cursor (requerida por Qt en X11) se empaqueta dentro del ejecutable
LIB=packaging/libs/libxcb-cursor.so.0
if [ ! -f "$LIB" ]; then
  mkdir -p packaging/libs
  SYS=$(ldconfig -p 2>/dev/null | awk '/libxcb-cursor.so.0 /{print $NF; exit}')
  if [ -n "$SYS" ]; then
    cp -L "$SYS" "$LIB"
  elif command -v apt >/dev/null; then
    TMP=$(mktemp -d)
    (cd "$TMP" && apt download libxcb-cursor0 >/dev/null 2>&1 \
      && { [ -f libxcb-cursor0.tar.gz ] && tar xzf libxcb-cursor0.tar.gz || true; } \
      && for d in $(find . -name '*.deb'); do dpkg -x "$d" x; done)
    cp -L "$TMP"/x/usr/lib/*/libxcb-cursor.so.0 "$LIB" 2>/dev/null || true
    rm -rf "$TMP"
  fi
  [ -f "$LIB" ] || echo "Aviso: no se pudo obtener libxcb-cursor; instálala con: sudo apt install libxcb-cursor0"
fi
.venv/bin/pyinstaller packaging/MDEmeeh.spec --noconfirm --distpath dist --workpath build --log-level WARN

# Poda de módulos Qt que la app no usa
QT="dist/MDEmeeh/_internal/PySide6/Qt"
rm -rf "$QT/qml"
rm -rf "$QT/plugins/qmltooling" "$QT/plugins/imageformats/libqpdf.so"
find dist/MDEmeeh/_internal \( -name 'libQt6Location*' -o -name 'libQt6QuickVectorImage*' \) -delete
find "$QT/lib" \( -name 'libQt6Quick3D*' -o -name 'libQt6QuickControls2*' -o -name 'libQt6QuickDialogs2*' \
  -o -name 'libQt6LabsStyleKit*' -o -name 'libQt6Graphs*' -o -name 'libQt6Pdf*' -o -name 'libQt6ShaderTools*' \
  -o -name 'libQt6QuickTimeline*' -o -name 'libQt6QuickParticles*' -o -name 'libQt6QuickShapes*' \
  -o -name 'libQt6Quick3DPhysics*' -o -name 'libQt6Charts*' -o -name 'libQt6DataVisualization*' \) -delete
find "$QT/translations" -maxdepth 1 -name '*.qm' ! -name '*_es.qm' ! -name '*_en.qm' -delete
find "$QT/translations/qtwebengine_locales" -name '*.pak' ! -name 'es*.pak' ! -name 'en-US.pak' -delete

# Verifica que no falte ninguna librería
MISSING=$(cd dist/MDEmeeh/_internal && LD_LIBRARY_PATH="$PWD:$PWD/PySide6/Qt/lib" \
  find . -name '*.so*' -exec ldd {} \; 2>/dev/null | grep 'not found' | sort -u || true)
if [ -n "$MISSING" ]; then echo "Faltan librerías:"; echo "$MISSING"; exit 1; fi
du -sh dist/MDEmeeh
echo "Listo: dist/MDEmeeh/MDEmeeh"
