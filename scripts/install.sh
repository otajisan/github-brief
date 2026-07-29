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
export GB_OUT="$OUTPUT_DIR"
# launchd GUI jobs get a minimal PATH; include where claude/gh/python3 live.
export GB_PATH_ENV="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

python3 "$GB_ROOT/scripts/gen_plists.py" "$AGENTS"

for label in com.github-brief.daily com.github-brief.weekly; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
  echo "loaded: $label"
done

echo
echo "Scheduled jobs:"
launchctl list | grep github-brief || true
echo
echo "Run once now:  launchctl kickstart -k gui/$(id -u)/com.github-brief.daily"
echo "Uninstall:     $GB_ROOT/scripts/uninstall.sh"
