#!/usr/bin/env bash
# Remove every github-brief launchd job (scheduled briefs + the hub server).
set -euo pipefail
AGENTS="$HOME/Library/LaunchAgents"
for plist in "$AGENTS"/com.github-brief.*.plist; do
  [[ -e "$plist" ]] || continue
  label="$(basename "$plist" .plist)"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$plist"
  echo "removed: $label"
done
