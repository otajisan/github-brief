#!/usr/bin/env bash
# =============================================================================
# command: pr-brief
#   github-brief pr-brief daily    # review queue + PRs merged since last day
#   github-brief pr-brief weekly   # weekly release / newly-opened summary
#
# Heartbeat-style loop. Deterministic parts (window, gh queries, Slack) run in
# shell; Claude only summarizes each PR and renders the HTML/Slack body.
# Supports one or many repositories (config REPOS).
# =============================================================================
set -euo pipefail

CMD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GB_ROOT="$(cd "$CMD_DIR/../.." && pwd)"
# shellcheck source=/dev/null
source "$GB_ROOT/lib/common.sh"
gb::load_config

MODE="${1:-}"
if [[ "$MODE" != "daily" && "$MODE" != "weekly" ]]; then
  echo "usage: github-brief pr-brief {daily|weekly}" >&2
  exit 2
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
DATE_TAG="$(date +%Y%m%d)"
export GB_LOG="$OUTPUT_DIR/logs/pr-brief-${MODE}-${STAMP}.log"

read -r SINCE UNTIL <<<"$(gb::iso_window "$MODE")"
gb::log "pr-brief $MODE  window: $SINCE .. $UNTIL"
gb::log "repos: $(echo "${REPOS[*]}")"

HTML_OUT="$OUTPUT_DIR/pr-brief-${MODE}-${DATE_TAG}.html"
SLACK_TXT="$OUTPUT_DIR/slack-pr-brief-${MODE}-${DATE_TAG}.txt"
rm -f "$SLACK_TXT"

PROMPT="$(gb::render "$CMD_DIR/prompts/${MODE}.md" \
  "REPOS=$(gb::repos_lines)" \
  "BASE=$BASE_BRANCH" \
  "REVIEW_FILTER=$REVIEW_FILTER" \
  "SINCE=$SINCE" \
  "UNTIL=$UNTIL" \
  "HTML_OUT=$HTML_OUT" \
  "SLACK_TXT=$SLACK_TXT" \
  "PORT=$SERVE_PORT")"

gb::log "running claude ($MODEL)…"
if gb::run_claude "$PROMPT" >>"$GB_LOG" 2>&1; then
  gb::update_index "$HTML_OUT"
  gb::post_slack "$SLACK_TXT"
  gb::log "done: $HTML_OUT"
else
  gb::log "ERROR: claude failed (see $GB_LOG)"
  gb::notify_failure "github-brief pr-brief ($MODE) failed. log: $GB_LOG"
  exit 1
fi
