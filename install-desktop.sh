#!/usr/bin/env bash
# Instala MDEmeeh (ejecutable de dist/) para el usuario actual y lo agrega al menú de aplicaciones.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -x "$DIR/dist/MDEmeeh/MDEmeeh" ] || "$DIR/build.sh"

APPDIR="$HOME/.local/opt/MDEmeeh"
rm -rf "$APPDIR"
mkdir -p "$HOME/.local/opt" "$HOME/.local/bin" "$HOME/.local/share/applications" \
         "$HOME/.local/share/icons/hicolor/scalable/apps"
cp -r "$DIR/dist/MDEmeeh" "$APPDIR"
cp "$DIR/emeeh_markdown/static/icon.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/mdemeeh.svg"
ln -sf "$APPDIR/MDEmeeh" "$HOME/.local/bin/mdemeeh"

rm -f "$HOME/.local/share/applications/emeeh-markdown.desktop"
cat > "$HOME/.local/share/applications/mdemeeh.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=MDEmeeh
GenericName=Editor de Markdown
Comment=Editor de Markdown WYSIWYG con modo oscuro y tablas
Exec="$APPDIR/MDEmeeh" %F
Icon=mdemeeh
Terminal=false
Categories=Office;TextEditor;
Keywords=markdown;md;editor;notas;typora;emeeh;
MimeType=text/markdown;text/x-markdown;
StartupWMClass=MDEmeeh
DESK
chmod +x "$HOME/.local/share/applications/mdemeeh.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
xdg-mime default mdemeeh.desktop text/markdown 2>/dev/null || true
echo "MDEmeeh instalado en $APPDIR"
