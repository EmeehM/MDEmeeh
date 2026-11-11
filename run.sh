#!/usr/bin/env bash
# Lanza Emeeh Markdown. Uso: ./run.sh [archivo.md]
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Creando entorno virtual e instalando dependencias…"
  python3 -m venv "$DIR/.venv" && "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt" || exit 1
fi
cd "$DIR" && exec "$DIR/.venv/bin/python" -m emeeh_markdown "$@"
