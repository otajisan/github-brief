#!/usr/bin/env bash
# =============================================================================
# command: pr-brief
#   github-brief pr-brief daily    # review queue + PRs merged since last day
#   github-brief pr-brief weekly   # weekly release / newly-opened summary
#
# Heartbeat-style loop. Everything breakable runs in shell: the time window,
# the gh queries, the aggregation (counts / per-day buckets / type breakdown)
# and the chart SVG. Claude only writes the per-PR summaries, the highlights
# and the page around them — it never fetches, counts, or draws.
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

# GB_AS_OF=YYYY-MM-DD backfills the brief of that day (window, file names and
# the date in the Slack title), e.g. after a run failed on a usage limit.
if [[ -n "${GB_AS_OF:-}" ]]; then
  if [[ ! "$GB_AS_OF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "GB_AS_OF must be YYYY-MM-DD: $GB_AS_OF" >&2
    exit 2
  fi
  DATE_TAG="${GB_AS_OF//-/}"
else
  DATE_TAG="$(date +%Y%m%d)"
fi
BRIEF_DATE="${DATE_TAG:0:4}/${DATE_TAG:4:2}/${DATE_TAG:6:2}"
STAMP="$(date +%Y%m%d-%H%M%S)"
export GB_LOG="$OUTPUT_DIR/logs/pr-brief-${MODE}-${STAMP}.log"
export GB_FAILURE_CONTEXT="github-brief pr-brief ($MODE)"   # read by gb::_on_exit
gb::guard_runtime          # a hang must fail loudly, not wedge the schedule
                           # (and gb::_on_exit makes a fast death just as loud)

read -r SINCE UNTIL <<<"$(gb::iso_window "$MODE")"
gb::log "pr-brief $MODE  window: $SINCE .. $UNTIL${GB_AS_OF:+  (backfill as of $GB_AS_OF)}"
gb::log "repos: ${REPOS[*]}"

# --- 0. connectivity --------------------------------------------------------
# The schedule and the Mac's sleep cycle are unrelated: launchd fires a missed
# job on wake, and this point is reached before Wi-Fi is back. Wait for the API
# instead of losing the brief on the first query.
if ! gb::wait_for_network; then
  gb::notify_failure "github-brief pr-brief ($MODE): api.github.com unreachable after ${NETWORK_WAIT_SECONDS:-180}s — run aborted before fetching. log: $GB_LOG"
  exit 1
fi

BASE_NAME="pr-brief-${MODE}-${DATE_TAG}"
HTML_OUT="$OUTPUT_DIR/${BASE_NAME}.html"
SLACK_TXT="$OUTPUT_DIR/slack-${BASE_NAME}.txt"
BUNDLE="$OUTPUT_DIR/${BASE_NAME}.bundle.json"
METRICS="$OUTPUT_DIR/${BASE_NAME}.metrics.json"
META="$OUTPUT_DIR/${BASE_NAME}.meta.json"
CHARTS="$OUTPUT_DIR/${BASE_NAME}.charts.html"
TMP_DIR="$OUTPUT_DIR/tmp/${BASE_NAME}"
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
rm -f "$SLACK_TXT"

# --- 1. fetch: the gh queries stay here, never in a prompt -------------------
COLLECT_ARGS=()
for repo in "${REPOS[@]}"; do
  slug="${repo//\//__}"
  if [[ "$MODE" == "daily" ]]; then
    gb::log "fetch: $repo review queue ($REVIEW_FILTER)"
    gb::fetch_prs "$repo" "$TMP_DIR/review-${slug}.json" \
      --state open --search "$REVIEW_FILTER"
    COLLECT_ARGS+=(--file "review:${repo}:$TMP_DIR/review-${slug}.json")
  else
    gb::log "fetch: $repo opened in window"
    gb::fetch_prs "$repo" "$TMP_DIR/created-${slug}.json" \
      --state all --search "created:${SINCE}..${UNTIL}"
    COLLECT_ARGS+=(--file "created:${repo}:$TMP_DIR/created-${slug}.json")
  fi

  gb::log "fetch: $repo merged into $BASE_BRANCH"
  gb::fetch_prs "$repo" "$TMP_DIR/merged-${slug}.json" \
    --state merged --base "$BASE_BRANCH" --search "merged:${SINCE}..${UNTIL}"
  COLLECT_ARGS+=(--file "merged:${repo}:$TMP_DIR/merged-${slug}.json")
done

# --- 2. aggregate: every number in the brief is computed here ----------------
PREV_ARGS=()
PREV_METRICS="$(gb::prev_metrics "$MODE" "$METRICS")"
if [[ -n "$PREV_METRICS" ]]; then
  gb::log "delta base: $(basename "$PREV_METRICS")"
  PREV_ARGS=(--prev-metrics "$PREV_METRICS")
fi

COUNTS="$(gb::collect_prs \
  --mode "$MODE" --since "$SINCE" --until "$UNTIL" --base "$BASE_BRANCH" \
  --tz-offset-hours "$TZ_OFFSET_HOURS" --date-tag "$DATE_TAG" \
  --html "$(basename "$HTML_OUT")" \
  --body-max-chars "${BODY_MAX_CHARS:-1200}" \
  --out-bundle "$BUNDLE" --out-metrics "$METRICS" --out-meta "$META" \
  ${PREV_ARGS[@]+"${PREV_ARGS[@]}"} "${COLLECT_ARGS[@]}")"
gb::log "aggregated: $COUNTS"

# --- 3. charts: pre-rendered, so the model never draws or counts -------------
if [[ "$MODE" == "weekly" ]]; then
  gb::render_charts "$METRICS" "$CHARTS"
  gb::log "charts: $(basename "$CHARTS")"
fi

# --- 4. the fuzzy part ------------------------------------------------------
PROMPT="$(gb::render "$CMD_DIR/prompts/${MODE}.md" \
  "REPOS=$(gb::repos_lines)" \
  "BASE=$BASE_BRANCH" \
  "SINCE=$SINCE" \
  "BRIEF_DATE=$BRIEF_DATE" \
  "UNTIL=$UNTIL" \
  "WINDOW=$(gb::window_label "$SINCE" "$UNTIL")" \
  "DATA_JSON=$BUNDLE" \
  "COUNTS=$COUNTS" \
  "HTML_OUT=$HTML_OUT" \
  "HTML_NAME=$(basename "$HTML_OUT")" \
  "SLACK_TXT=$SLACK_TXT" \
  "PORT=$SERVE_PORT")"

gb::log "running claude ($MODEL)…"
if gb::run_claude "$PROMPT" >>"$GB_LOG" 2>&1; then
  if [[ "$MODE" == "weekly" ]]; then
    gb::inject_charts "$HTML_OUT" "$CHARTS"
  fi
  gb::rebuild_site
  slack_ok=1
  gb::post_slack "$SLACK_TXT" || slack_ok=0   # already logged + warned
  rm -rf "$TMP_DIR"
  gb::log "done: $HTML_OUT"
  gb::log "index: $OUTPUT_DIR/index.html"
  [[ "$slack_ok" == 1 ]] || exit 1
else
  gb::log "ERROR: claude failed (see $GB_LOG)"
  gb::notify_failure "github-brief pr-brief ($MODE) failed. log: $GB_LOG"
  exit 1
fi
