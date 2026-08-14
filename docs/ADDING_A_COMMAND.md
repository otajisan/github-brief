# Adding a new command

**English** | [日本語](ADDING_A_COMMAND.ja.md)

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
gb::guard_runtime          # a hang must fail loudly, not wedge the schedule

HTML_OUT="$OUTPUT_DIR/stale-prs-$(date +%Y%m%d).html"
SLACK_TXT="$OUTPUT_DIR/slack-stale-prs-$(date +%Y%m%d).txt"

PROMPT="$(gb::render "$CMD_DIR/prompts/default.md" \
  "REPOS=$(gb::repos_lines)" "HTML_OUT=$HTML_OUT" "SLACK_TXT=$SLACK_TXT" "PORT=$SERVE_PORT")"

if gb::run_claude "$PROMPT" >>"$GB_LOG" 2>&1; then
  gb::rebuild_site            # index.html hub + nav on every archived page
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
| `gb::guard_runtime [sec]` | Watchdog: kill + Slack-warn a run that hangs (`RUN_TIMEOUT_SECONDS`). Also arms the EXIT trap that Slack-warns any non-zero exit |
| `gb::wait_for_network [sec]` | Block until `api.github.com` answers (`NETWORK_WAIT_SECONDS`); returns 1 if it never does |
| `gb::repos_lines` | Print configured repos, one per line |
| `gb::iso_window daily\|weekly` | Deterministic `SINCE UNTIL` (ISO8601 + tz) |
| `gb::window_label since until` | Human-facing window (`2026/07/22 14:30 〜 07/29 10:30`) |
| `gb::fetch_prs repo out.json …` | `gh pr list --json …` dump, retried (`GH_RETRIES`), written atomically |
| `gb::collect_prs …` | Merge dumps → `bundle.json` + `metrics.json` + `.meta.json` |
| `gb::render_charts metrics out` | Pre-rendered KPI + chart fragment |
| `gb::prev_metrics mode current` | Newest earlier metrics file (previous-period delta) |
| `gb::render tpl KEY=VAL…` | Replace `@@KEY@@` in a prompt template |
| `gb::run_claude "prompt"` | Headless Claude run (read-only gh + Write, bounded) |
| `gb::inject_charts html frag` | Splice a chart block into `<!-- gb:charts -->` |
| `gb::rebuild_site` | Rebuild the `index.html` hub + nav on archived pages |
| `gb::post_slack txt` | Post a text file to the Slack webhook (no-op if unset) |
| `gb::notify_failure "msg"` | Send a warning to Slack |

### Appearing in the history hub

`lib/build_site.py` currently indexes pages named
`pr-brief-<daily|weekly>-<YYYYMMDD>.html` with a sibling `<same-stem>.meta.json`
(written by `gb::collect_prs --out-meta`). A new command's pages show up in the
hub once you extend `NAME_RE` / `MODE_JA` in `lib/build_site.py` to know about
it; until then, link to your page from your own Slack body. Keep one archived
file per run — never overwrite yesterday's page.

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
