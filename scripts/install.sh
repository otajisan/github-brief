#!/usr/bin/env bash
# Register github-brief scheduled jobs with macOS launchd.
# Prereqs: config.local.sh edited, `gh auth login` done, `claude` logged in.
set -euo pipefail

GB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$GB_ROOT/lib/common.sh"
gb::load_config

chmod +x "$GB_ROOT/bin/github-brief" "$GB_ROOT"/scripts/*.sh

AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$OUTPUT_DIR/logs"

export GB_BIN="$GB_ROOT/bin/github-brief"
export GB_SERVE="$GB_ROOT/scripts/serve.sh"
export SERVE_AT_LOGIN="${SERVE_AT_LOGIN:-0}"
export GB_OUT="$OUTPUT_DIR"
# launchd GUI jobs get a minimal PATH; include where claude/gh/python3 live.
export GB_PATH_ENV="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Unload everything first so a job dropped from the config (e.g. the hub server
# after SERVE_AT_LOGIN is turned off) does not linger from a previous install.
for plist in "$AGENTS"/com.github-brief.*.plist; do
  [[ -e "$plist" ]] || continue
  launchctl bootout "gui/$(id -u)/$(basename "$plist" .plist)" 2>/dev/null || true
  rm -f "$plist"
done

labels="$(python3 "$GB_ROOT/scripts/gen_plists.py" "$AGENTS")"
while IFS= read -r label; do
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
  echo "loaded: $label"
done <<<"$labels"

echo
echo "Scheduled jobs:"
launchctl list | grep github-brief || true
echo
echo "Run once now:  launchctl kickstart -k gui/$(id -u)/com.github-brief.daily"
if [[ "$SERVE_AT_LOGIN" == "1" ]]; then
  echo "History hub:   http://localhost:${SERVE_PORT:-8787}/index.html (always on)"
fi
echo "Uninstall:     $GB_ROOT/scripts/uninstall.sh"
