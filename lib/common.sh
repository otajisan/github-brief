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
  # Marker for "this failure was already reported". A file rather than a
  # variable because the watchdog below runs in a subshell; it sees the same
  # $$, so both sides agree on the path.
  GB_NOTIFY_MARKER="${TMPDIR:-/tmp}/github-brief-notified.$$"
  export GB_NOTIFY_MARKER
  rm -f "$GB_NOTIFY_MARKER"
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
  trap 'gb::_on_exit' EXIT
}

gb::disarm_runtime() {
  [[ -n "${GB_WATCHDOG_PID:-}" ]] || return 0
  kill "$GB_WATCHDOG_PID" 2>/dev/null || true
  GB_WATCHDOG_PID=""
}

# gb::_on_exit   (EXIT trap installed by gb::guard_runtime — not called directly)
# The watchdog above only catches hangs. This catches the opposite failure: a
# step that dies fast. Under `set -e` everything before the Claude call — the
# gh fetch, the aggregation, the charts — aborted the run with no log line and
# no Slack warning, so a failed brief looked exactly like a brief nobody had
# read yet. Report any non-zero exit that nothing else has reported.
gb::_on_exit() {
  local rc=$?
  gb::disarm_runtime
  if [[ "$rc" -ne 0 && ! -f "${GB_NOTIFY_MARKER:-/nonexistent}" ]]; then
    gb::log "ERROR: ${GB_FAILURE_CONTEXT:-github-brief} exited $rc"
    gb::notify_failure \
      "${GB_FAILURE_CONTEXT:-github-brief}: failed with exit $rc (log: ${GB_LOG:-n/a})"
  fi
  [[ -n "${GB_NOTIFY_MARKER:-}" ]] && rm -f "$GB_NOTIFY_MARKER"
  return 0
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

# gb::wait_for_network [max_seconds]   (default NETWORK_WAIT_SECONDS, else 180)
# launchd fires a missed job the moment the Mac wakes, which is routinely before
# Wi-Fi is back — the first gh call then dies with "error connecting to
# api.github.com" and that day's brief is simply lost. Wait for the API instead.
# The probe is `gh api rate_limit`: it exercises DNS, TLS and auth in one call,
# and that endpoint is itself exempt from the rate limit.
gb::wait_for_network() {
  local limit="${1:-${NETWORK_WAIT_SECONDS:-180}}"
  local waited=0 delay=5
  while :; do
    if "${GH_BIN:-gh}" api rate_limit --silent >/dev/null 2>&1; then
      if [[ "$waited" -gt 0 ]]; then
        gb::log "network: api.github.com reachable after ${waited}s"
      fi
      return 0
    fi
    if [[ "$waited" -ge "$limit" ]]; then
      gb::log "network: api.github.com still unreachable after ${waited}s"
      return 1
    fi
    gb::log "network: api.github.com unreachable, retry in ${delay}s (${waited}/${limit}s)"
    sleep "$delay"
    waited=$((waited + delay))
    if [[ "$delay" -lt 30 ]]; then delay=$((delay * 2)); fi
  done
}

# gb::fetch_prs <repo> <out.json> [extra gh args…]
# Retried: once the schedule is unattended, a single dropped packet must not
# cost the whole brief. Writes through a .part file so a failed attempt cannot
# leave a truncated (or empty) .json behind for a later step to read as valid.
gb::fetch_prs() {
  local repo="$1" out="$2"; shift 2
  local attempts="${GH_RETRIES:-3}" try=1 delay=5
  while :; do
    if "${GH_BIN:-gh}" pr list --repo "$repo" \
        --json "$GB_PR_FIELDS" --limit "${GH_LIMIT:-200}" "$@" >"$out.part"; then
      mv "$out.part" "$out"
      return 0
    fi
    rm -f "$out.part"
    if [[ "$try" -ge "$attempts" ]]; then
      gb::log "fetch: $repo failed after ${attempts} attempt(s)"
      return 1
    fi
    gb::log "fetch: $repo failed (attempt ${try}/${attempts}), retry in ${delay}s"
    sleep "$delay"
    try=$((try + 1))
    delay=$((delay * 2))
  done
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

# gb::_slack_send <json-payload>
# POSTs to the webhook and succeeds only on HTTP 200 with body "ok". curl's own
# exit status is not enough: a revoked webhook (403/404) or a rejected payload
# (400 invalid_payload, msg_too_long, …) still exits 0. On failure the status
# and Slack's reason are printed to stderr; the URL never is.
gb::_slack_send() {
  local resp
  resp="$(curl -sS --max-time 30 -w $'\n%{http_code}' -X POST \
    -H 'Content-type: application/json' --data "$1" "$SLACK_WEBHOOK_URL" 2>&1)" || {
    printf 'curl error: %s\n' "${resp%%$'\n'*}" >&2; return 1; }
  local code="${resp##*$'\n'}" body="${resp%$'\n'*}"
  [[ "$code" == "200" && "$body" == "ok" ]] && return 0
  printf 'HTTP %s: %s\n' "$code" "${body:0:200}" >&2
  return 1
}

# gb::post_slack <file.txt>
# Posts the brief. A missing body or a rejected post is a failure of the run's
# main deliverable, so it is logged and reported via gb::notify_failure (which
# reaches Slack when only this one message was rejected, e.g. msg_too_long).
gb::post_slack() {
  local txt="$1"
  if [[ -z "${SLACK_WEBHOOK_URL:-}" ]]; then gb::log "slack: not configured, skipping"; return 0; fi
  if [[ ! -f "$txt" ]]; then
    gb::log "slack: body missing ($txt)"
    gb::notify_failure "${GB_FAILURE_CONTEXT:-github-brief}: Slack body was not generated ($txt). log: ${GB_LOG:-n/a}"
    return 0
  fi
  local payload err
  payload="$(python3 - "$txt" <<'PY'
import json, sys
print(json.dumps({"text": open(sys.argv[1], encoding="utf-8").read()}, ensure_ascii=False))
PY
)"
  if err="$(gb::_slack_send "$payload" 2>&1)"; then
    gb::log "slack: sent"
  else
    gb::log "slack: send failed ($err)"
    gb::notify_failure "${GB_FAILURE_CONTEXT:-github-brief}: Slack post was rejected ($err). log: ${GB_LOG:-n/a}"
  fi
}

# gb::notify_failure "<message>"
# The single place a warning is sent. Drops the marker first so gb::_on_exit
# does not send a second warning for the same failure — including when the
# watchdog reports from its subshell and then kills this run. The body goes
# through python3 rather than string interpolation so a message containing a
# quote or a newline cannot produce invalid JSON and silently post nothing.
gb::notify_failure() {
  if [[ -n "${GB_NOTIFY_MARKER:-}" ]]; then
    : >"$GB_NOTIFY_MARKER" 2>/dev/null || true
  fi
  [[ -n "${SLACK_WEBHOOK_URL:-}" ]] || return 0
  local payload
  payload="$(python3 -c 'import json,sys; print(json.dumps({"text": ":warning: " + sys.argv[1]}, ensure_ascii=False))' "$1")" || return 0
  local err
  err="$(gb::_slack_send "$payload" 2>&1)" || gb::log "slack: warning not delivered ($err)"
  return 0
}
