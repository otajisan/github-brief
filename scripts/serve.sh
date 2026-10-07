#!/usr/bin/env bash
# Serve generated HTML at http://localhost:PORT/index.html
set -euo pipefail
GB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$GB_ROOT/lib/common.sh"
gb::load_config
PORT="${1:-${SERVE_PORT:-8787}}"
# Loopback only: the pages summarise private PRs and must not reach the LAN.
echo "Serving $OUTPUT_DIR at http://localhost:$PORT/index.html"
exec python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$OUTPUT_DIR"
