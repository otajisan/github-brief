#!/usr/bin/env bash
# =============================================================================
# github-brief shared library
#
# Reusable helpers for every command. Design principle (loop engineering):
# keep deterministic, breakable logic (dates, gh queries, Slack) here in shell;
# delegate only the fuzzy parts (summaries, HTML rendering) to Claude.
#
# All functions are namespaced gb::* and safe to source multiple times.
# =============================================================================
set -euo pipefail

GB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export GB_ROOT

# --- config -----------------------------------------------------------------
gb::load_config() {
  local cfg="$GB_ROOT/config.local.sh"
  if [[ ! -f "$cfg" ]]; then
    echo "ERROR: config.local.sh not found." >&2
    echo "  cp config.example.sh config.local.sh   # then edit it" >&2
    exit 1
  fi
  # shellcheck source=/dev/null
  source "$cfg"
  : "${REPOS:?REPOS is not set in config.local.sh}"
  : "${OUTPUT_DIR:?OUTPUT_DIR is not set in config.local.sh}"
  mkdir -p "$OUTPUT_DIR" "$OUTPUT_DIR/logs"
}

# --- logging ----------------------------------------------------------------
gb::log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "${GB_LOG:-/dev/null}" >&2 ; }

# --- repos ------------------------------------------------------------------
gb::repos_lines() { printf '%s\n' "${REPOS[@]}"; }

# --- time windows -----------------------------------------------------------
# gb::iso_window daily|weekly   ->   prints "SINCE UNTIL" (ISO8601 w/ tz offset)
gb::iso_window() {
  python3 - "$1" "$TZ_OFFSET_HOURS" \
    "${WEEKLY_LOOKBACK_DAYS:-7}" "${WEEKLY_HOUR:-10}" "${WEEKLY_MINUTE:-30}" \
    "${WEEKLY_START_HOUR:-14}" "${WEEKLY_START_MINUTE:-30}" <<'PY'
import sys
from datetime import datetime, timedelta, timezone
mode = sys.argv[1]
tz = timezone(timedelta(hours=int(sys.argv[2])))
lookback, wh, wm, sh, sm = (int(x) for x in sys.argv[3:8])
now = datetime.now(tz)
def iso(d):
    s = d.strftime("%Y-%m-%dT%H:%M:%S%z")
    return s[:-2] + ":" + s[-2:]
if mode == "daily":
    t0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = t0 - timedelta(days=3 if now.weekday() == 0 else 1)  # Monday covers Fri-Sun
    until = t0
else:  # weekly
    until = now.replace(hour=wh, minute=wm, second=0, microsecond=0)
    since = (until - timedelta(days=lookback)).replace(hour=sh, minute=sm, second=0, microsecond=0)
print(iso(since), iso(until))
PY
}

# --- prompt templating ------------------------------------------------------
# gb::render <template_file> KEY=VALUE KEY=VALUE ...   ->   prints rendered text
# Replaces @@KEY@@ with VALUE (pure bash, safe for slashes/&/multiline values).
gb::render() {
  local tpl="$1"; shift
  local content; content="$(cat "$tpl")"
  local pair k v
  for pair in "$@"; do
    k="${pair%%=*}"; v="${pair#*=}"
    content="${content//@@${k}@@/$v}"
  done
  printf '%s' "$content"
}

# --- claude runner ----------------------------------------------------------
# gb::run_claude "<prompt>"   (stdout = claude json; caller redirects to log)
gb::run_claude() {
  "$CLAUDE_BIN" -p "$1" \
    --model "$MODEL" \
    --max-turns "$MAX_TURNS" \
    --allowedTools "Bash(gh:*),Read,Write" \
    --permission-mode acceptEdits \
    --add-dir "$OUTPUT_DIR" \
    --output-format json
}

# --- outputs ----------------------------------------------------------------
gb::update_index() {
  [[ -f "$1" ]] && cp -f "$1" "$OUTPUT_DIR/index.html"
}

gb::post_slack() {
  local txt="$1"
  if [[ -z "${SLACK_WEBHOOK_URL:-}" ]]; then gb::log "slack: not configured, skipping"; return 0; fi
  if [[ ! -f "$txt" ]]; then gb::log "slack: body missing ($txt)"; return 0; fi
  local payload
  payload="$(python3 - "$txt" <<'PY'
import json, sys
print(json.dumps({"text": open(sys.argv[1], encoding="utf-8").read()}, ensure_ascii=False))
PY
)"
  if curl -s -X POST -H 'Content-type: application/json' --data "$payload" "$SLACK_WEBHOOK_URL" >/dev/null; then
    gb::log "slack: sent"
  else
    gb::log "slack: send failed"
  fi
}

gb::notify_failure() {
  [[ -z "${SLACK_WEBHOOK_URL:-}" ]] && return 0
  curl -s -X POST -H 'Content-type: application/json' \
    --data "{\"text\":\":warning: $1\"}" "$SLACK_WEBHOOK_URL" >/dev/null || true
}
