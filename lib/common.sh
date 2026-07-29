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

# --- runtime guard ----------------------------------------------------------
# gb::guard_runtime [seconds]   (default RUN_TIMEOUT_SECONDS, else 3600)
# Backstop for hangs. A run that blocks instead of failing — a wedged CLI, a
# stuck pipe — keeps launchd's job in "running" state forever, which silently
# skips every later schedule and produces no log and no Slack warning. This
# arms a watchdog that kills the run and shouts. MAX_TURNS bounds cost; this
# bounds wall-clock. Installs an EXIT trap, so call it once, early.
gb::guard_runtime() {
  local limit="${1:-${RUN_TIMEOUT_SECONDS:-3600}}"
  local target=$$
  (
    waited=0
    while [[ "$waited" -lt "$limit" ]]; do
      sleep 5
      waited=$((waited + 5))
      kill -0 "$target" 2>/dev/null || exit 0
    done
    gb::log "TIMEOUT: run exceeded ${limit}s — terminating"
    gb::notify_failure "github-brief: run exceeded ${limit}s and was killed (log: ${GB_LOG:-n/a})"
    # Take the whole tree down: killing only the script would orphan a wedged
    # child (claude, gh) and leave it running. Under launchd the script is its
    # own process-group leader, so the group signal reaches every descendant;
    # otherwise fall back to direct children + the script itself.
    if [[ "$(ps -o pgid= -p "$target" 2>/dev/null | tr -d ' ')" == "$target" ]]; then
      kill -TERM -"$target" 2>/dev/null || true
      sleep 10
      kill -KILL -"$target" 2>/dev/null || true
    else
      pkill -TERM -P "$target" 2>/dev/null || true
      kill -TERM "$target" 2>/dev/null || true
      sleep 10
      pkill -KILL -P "$target" 2>/dev/null || true
      kill -KILL "$target" 2>/dev/null || true
    fi
  ) &
  GB_WATCHDOG_PID=$!
  trap 'gb::disarm_runtime' EXIT
}

gb::disarm_runtime() {
  [[ -n "${GB_WATCHDOG_PID:-}" ]] || return 0
  kill "$GB_WATCHDOG_PID" 2>/dev/null || true
  GB_WATCHDOG_PID=""
}

# --- repos ------------------------------------------------------------------
gb::repos_lines() { printf '%s\n' "${REPOS[@]}"; }

# --- time windows -----------------------------------------------------------
# gb::iso_window daily|weekly   ->   prints "SINCE UNTIL" (ISO8601 w/ tz offset)
# The program lives in lib/iso_window.py rather than a here-document: bash routes
# a here-document larger than the pipe buffer through a temp file, and that path
# can block on macOS — a scheduled run would hang instead of failing.
gb::iso_window() {
  python3 "$GB_ROOT/lib/iso_window.py" "$1" "$TZ_OFFSET_HOURS" \
    "${WEEKLY_LOOKBACK_DAYS:-7}" "${WEEKLY_HOUR:-10}" "${WEEKLY_MINUTE:-30}" \
    "${WEEKLY_START_HOUR:-14}" "${WEEKLY_START_MINUTE:-30}"
}

# gb::window_label <since> <until>  ->  "2026/07/22 14:30 〜 07/29 10:30"
# Human-facing form of the window; prompts print this instead of raw ISO stamps.
gb::window_label() {
  python3 "$GB_ROOT/lib/iso_window.py" --label "$1" "$2"
}

# --- github data (deterministic: queries + JSON never go to the model) ------
# Fields every command needs. `body` is included so the model can summarize a
# PR straight from the bundle without spending a turn on `gh pr view`.
GB_PR_FIELDS="number,title,url,author,createdAt,updatedAt,mergedAt,state,isDraft,additions,deletions,changedFiles,labels,body"

# gb::fetch_prs <repo> <out.json> [extra gh args…]
gb::fetch_prs() {
  local repo="$1" out="$2"; shift 2
  "${GH_BIN:-gh}" pr list --repo "$repo" \
    --json "$GB_PR_FIELDS" --limit "${GH_LIMIT:-200}" "$@" >"$out"
}

# gb::collect_prs [args…]   -> bundle.json + metrics.json + meta.json
gb::collect_prs() { python3 "$GB_ROOT/lib/collect_prs.py" "$@"; }

# gb::render_charts <metrics.json> <out.html>   (self-contained SVG fragment)
gb::render_charts() {
  python3 "$GB_ROOT/lib/render_charts.py" --metrics "$1" --out "$2"
}

# gb::prev_metrics <mode> <current.metrics.json>  -> newest earlier metrics file
# Feeds the "前期比" delta; prints nothing when there is no history yet.
gb::prev_metrics() {
  local mode="$1" current="$2" i
  local files=("$OUTPUT_DIR"/pr-brief-"$mode"-*.metrics.json)
  for ((i = ${#files[@]} - 1; i >= 0; i--)); do
    [[ -f "${files[i]}" && "${files[i]}" != "$current" ]] || continue
    printf '%s\n' "${files[i]}"
    return 0
  done
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
# gb::inject_charts <page.html> <fragment.html>
# Splices a pre-rendered chart block into the page the model just wrote (at the
# <!-- gb:charts --> slot, or right after <body> as a fallback). Idempotent.
gb::inject_charts() {
  [[ -f "$1" && -f "$2" ]] || { gb::log "charts: nothing to inject"; return 0; }
  python3 "$GB_ROOT/lib/build_site.py" charts --html "$1" --fragment "$2"
}

# gb::rebuild_site
# Rebuilds index.html as the history hub and refreshes the nav bar on every
# archived brief, so older pages link forward to newer ones.
gb::rebuild_site() {
  python3 "$GB_ROOT/lib/build_site.py" nav --output-dir "$OUTPUT_DIR"
  python3 "$GB_ROOT/lib/build_site.py" index --output-dir "$OUTPUT_DIR"
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
