# Adding a new command

A "command" is a self-contained automation under `commands/<name>/`. Adding one
never requires editing `bin/github-brief` or existing commands.

Ideas that fit this harness: `stale-prs` (PRs idle > N days), `review-latency`
(time-to-first-review stats), `release-notes` (draft notes from merged PRs),
`issue-triage`, `deploy-digest`, etc.

## 1. Create the command directory

```
commands/stale-prs/
├── command.sh
└── prompts/            # optional, only if you delegate rendering to Claude
    └── default.md
```

## 2. Write `command.sh`

Use the shared library. Minimal skeleton:

```bash
#!/usr/bin/env bash
set -euo pipefail
CMD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GB_ROOT="$(cd "$CMD_DIR/../.." && pwd)"
# shellcheck source=/dev/null
source "$GB_ROOT/lib/common.sh"
gb::load_config

export GB_LOG="$OUTPUT_DIR/logs/stale-prs-$(date +%Y%m%d-%H%M%S).log"

HTML_OUT="$OUTPUT_DIR/stale-prs-$(date +%Y%m%d).html"
SLACK_TXT="$OUTPUT_DIR/slack-stale-prs-$(date +%Y%m%d).txt"

PROMPT="$(gb::render "$CMD_DIR/prompts/default.md" \
  "REPOS=$(gb::repos_lines)" "HTML_OUT=$HTML_OUT" "SLACK_TXT=$SLACK_TXT" "PORT=$SERVE_PORT")"

if gb::run_claude "$PROMPT" >>"$GB_LOG" 2>&1; then
  gb::update_index "$HTML_OUT"
  gb::post_slack "$SLACK_TXT"
else
  gb::notify_failure "github-brief stale-prs failed. log: $GB_LOG"
  exit 1
fi
```

It will immediately be runnable:

```bash
github-brief stale-prs
```

## Helpers available (`lib/common.sh`)

| Function | Purpose |
|---|---|
| `gb::load_config` | Source `config.local.sh`, ensure `OUTPUT_DIR` exists |
| `gb::log "msg"` | Timestamped log to `$GB_LOG` (stderr) |
| `gb::repos_lines` | Print configured repos, one per line |
| `gb::iso_window daily\|weekly` | Deterministic `SINCE UNTIL` (ISO8601 + tz) |
| `gb::render tpl KEY=VAL…` | Replace `@@KEY@@` in a prompt template |
| `gb::run_claude "prompt"` | Headless Claude run (read-only gh + Write, bounded) |
| `gb::update_index html` | Copy an HTML file to `index.html` |
| `gb::post_slack txt` | Post a text file to the Slack webhook (no-op if unset) |
| `gb::notify_failure "msg"` | Send a warning to Slack |

## 3. (Optional) schedule it

Add an entry to `JOBS` in `scripts/gen_plists.py`, then re-run
`scripts/install.sh`:

```python
JOBS = {
    ...,
    "com.github-brief.stale-prs": (["stale-prs"], {"Weekday": 1, "Hour": 9, "Minute": 30}),
}
```

## Conventions

- Human-facing output in the language your team uses; keep prompts explicit.
- Stay read-only unless there's a strong reason; keep the `--allowedTools`
  allowlist tight.
- Write outputs into `OUTPUT_DIR`, never into the repo.
