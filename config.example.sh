#!/usr/bin/env bash
# =============================================================================
# github-brief configuration (EXAMPLE)
#
#   cp config.example.sh config.local.sh   then edit config.local.sh
#   config.local.sh is gitignored so your repo names / webhook stay private.
# =============================================================================

# --- Target repositories (one or more) -------------------------------------
# Add as many as you manage. Format: "owner/repo".
export REPOS=(
  "owner/repo-a"
  "owner/repo-b"
)

# Base branch treated as "released" when merged.
export BASE_BRANCH="main"

# How "PRs to review" is defined (GitHub search qualifier):
#   review-requested:@me            -> requested directly from you
#   team-review-requested:ORG/TEAM  -> requested from your team
export REVIEW_FILTER="review-requested:@me"

# --- Delivery ---------------------------------------------------------------
# Slack Incoming Webhook URL. Leave empty ("") to skip Slack and only write HTML.
#   https://api.slack.com/messaging/webhooks
export SLACK_WEBHOOK_URL=""

# Where HTML + logs are written (kept OUTSIDE the repo so nothing private is committed).
export OUTPUT_DIR="$HOME/.local/share/github-brief"

# Port used by scripts/serve.sh to view HTML at http://localhost:PORT/index.html
export SERVE_PORT="8787"
# 1 = scripts/install.sh also registers a login item that keeps serve.sh running
# (loopback only), so the hub survives reboots. 0 = start serve.sh by hand.
export SERVE_AT_LOGIN="1"

# --- Claude Code ------------------------------------------------------------
export MODEL="claude-sonnet-5"     # cost-first: claude-haiku-4-5 / quality: claude-opus-4-8
export MAX_TURNS="30"              # Bounded Execution: per-run cost ceiling
export RUN_TIMEOUT_SECONDS="3600"  # wall-clock ceiling; a hung run is killed + Slack-warned
export CLAUDE_BIN="claude"
export GH_BIN="gh"

# --- Data collection (optional; defaults are built in) ----------------------
export GH_LIMIT="200"              # max PRs fetched per gh query
export BODY_MAX_CHARS="1200"       # PR body truncated to this before the model sees it

# --- Resilience (a scheduled run must survive a sleeping Mac) ---------------
# launchd fires a missed job the moment the Mac wakes — often before Wi-Fi is
# back. The run waits for api.github.com instead of dying on the first query.
export NETWORK_WAIT_SECONDS="180"  # wait this long for api.github.com before aborting
export GH_RETRIES="3"              # attempts per gh query before the run fails

# --- Time windows -----------------------------------------------------------
export TZ_OFFSET_HOURS="9"         # JST = 9

# --- Schedules (consumed by scripts/install.sh to generate launchd jobs) ----
# Daily brief
export DAILY_HOUR="9"
export DAILY_MINUTE="0"
export DAILY_WEEKDAYS="1 2 3 4 5"  # 1=Mon .. 7=Sun

# Weekly brief run time = end of the weekly window
export WEEKLY_WEEKDAY="5"          # 5 = Friday
export WEEKLY_HOUR="10"
export WEEKLY_MINUTE="30"
# Start of the weekly window, relative to the run time
export WEEKLY_LOOKBACK_DAYS="7"
export WEEKLY_START_HOUR="14"
export WEEKLY_START_MINUTE="30"
