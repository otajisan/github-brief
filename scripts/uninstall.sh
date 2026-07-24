#!/usr/bin/env bash
# Remove github-brief scheduled jobs from launchd.
set -euo pipefail
AGENTS="$HOME/Library/LaunchAgents"
for label in com.github-brief.daily com.github-brief.weekly; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$AGENTS/$label.plist"
  echo "removed: $label"
done
