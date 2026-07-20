#!/usr/bin/env bash
# ensure-venv.sh <name> — idempotent venv bootstrap for plugin skills.
# Venvs live inside the plugin dir so uninstalling the plugin removes them too.
set -euo pipefail
NAME="${1:?usage: ensure-venv.sh <name>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$NAME" in
  dsa) REQ="requirements/dsa.txt";;
  ta) REQ="requirements/ta.txt";;
  *) echo "unknown venv name: $NAME" >&2; exit 1;;
esac
VENV="$ROOT/.venvs/$NAME"
PY="$VENV/bin/python"
[ -x "$PY" ] && exit 0
python3 -m venv "$VENV"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r "$ROOT/$REQ"
echo "venv ready: $PY"
