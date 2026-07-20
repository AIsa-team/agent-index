#!/usr/bin/env bash
# ensure-data.sh — idempotent user-data seeding for the cio plugin.
# Copies bundled assets into the data dir ONLY where files are missing;
# user data lives outside the plugin dir so updates never touch it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DST="${AISA_DATA_DIR:-$HOME/.aisa/agents/cio}"
mkdir -p "$DST"
(cd "$ROOT/assets" && find . -type f) | while read -r f; do
  mkdir -p "$DST/$(dirname "$f")"
  [ -e "$DST/$f" ] || cp "$ROOT/assets/$f" "$DST/$f"
done
echo "data ready: $DST"
