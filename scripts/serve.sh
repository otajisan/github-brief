#!/usr/bin/env bash
# Serve generated HTML at http://localhost:PORT/index.html
set -euo pipefail
GB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$GB_ROOT/lib/common.sh"
gb::load_config
PORT="${1:-${SERVE_PORT:-8787}}"
# lib/serve.py: loopback only, Host-checked, *.html only, no access log.
exec python3 "$GB_ROOT/lib/serve.py" "$PORT" "$OUTPUT_DIR"
