# github-brief

**English** | [日本語](README.ja.md)

Automated briefs of your GitHub repository activity, delivered to Slack and a
local HTML page. Runs on your own machine via [Claude Code](https://claude.com/product/claude-code)
+ the [GitHub CLI](https://cli.github.com/) — no third-party server, no
connector, no data leaving your laptop except the Slack message you choose to
send.

The first bundled automation is **pr-brief**:

- **Daily (weekday morning):** the PRs waiting on your review, plus the PRs
  merged into your base branch since the previous day — each with a one-line
  summary of what it changes.
- **Weekly (e.g. Friday):** everything released and newly opened over the past
  week, with auto-generated highlights you can paste into a progress report,
  plus charts of the release week (releases per day, type breakdown, per repo,
  per author) and a comparison against the previous period.

Every run is archived, and `index.html` is a **history hub**: the latest weekly
and daily brief up front, then the full archive. Each page carries a nav bar, so
in a weekly meeting you can open the weekly summary and jump straight into the
daily briefs of that same week when someone asks for detail.

It supports **one or many repositories** and is built as a small harness so you
can add more activity automations over time (see
[docs/ADDING_A_COMMAND.md](docs/ADDING_A_COMMAND.md)).

> Why a harness and not one script? See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
> In short: deterministic work (dates, `gh` queries, aggregation, every number,
> the charts, Slack) stays in shell; only summarizing and the surrounding page
> are delegated to the model, under a strict read-only, cost-bounded
> configuration.

## Requirements

- macOS (scheduling uses `launchd`; the commands themselves are portable)
- `python3` (ships with macOS Command Line Tools)
- [`gh`](https://cli.github.com/) authenticated: `gh auth login`
- Claude Code CLI installed and logged in (`claude` runnable)
- A Slack [Incoming Webhook](https://api.slack.com/messaging/webhooks) URL (optional)

## Quick start

```bash
git clone https://github.com/otajisan/github-brief.git
cd github-brief
cp config.example.sh config.local.sh
$EDITOR config.local.sh          # set REPOS and SLACK_WEBHOOK_URL

chmod +x bin/github-brief scripts/*.sh

# try it once
./bin/github-brief pr-brief daily
./bin/github-brief pr-brief weekly

# view the HTML (index.html = history hub: latest + archive)
./scripts/serve.sh               # http://localhost:8787/index.html

# schedule it (weekday 09:00 daily, Friday 10:30 weekly by default)
./scripts/install.sh
```

Run a scheduled job immediately to test:

```bash
launchctl kickstart -k gui/$(id -u)/com.github-brief.daily
```

## Configuration

Everything environment-specific lives in `config.local.sh` (gitignored). Key
settings:

| Setting | Meaning |
|---|---|
| `REPOS` | Bash array of `owner/repo` to include (one or many) |
| `BASE_BRANCH` | Branch counted as "released" when merged (`main`) |
| `REVIEW_FILTER` | `review-requested:@me` or `team-review-requested:ORG/TEAM` |
| `SLACK_WEBHOOK_URL` | Incoming webhook; empty = HTML only |
| `OUTPUT_DIR` | Where HTML/logs go (outside the repo) |
| `MODEL` / `MAX_TURNS` | Model and per-run cost ceiling |
| `RUN_TIMEOUT_SECONDS` | Wall-clock ceiling; a hung run is killed and reported to Slack (default 3600) |
| `TZ_OFFSET_HOURS` | Timezone for windows (JST = 9) |
| `DAILY_*` / `WEEKLY_*` | Schedule + weekly window bounds |
| `GH_LIMIT` | Max PRs fetched per `gh` query (default 200) |
| `BODY_MAX_CHARS` | PR body truncation before the model sees it (default 1200) |

## Browsing history

`OUTPUT_DIR` accumulates one page per run, named
`pr-brief-<mode>-<YYYYMMDD>.html`, and `index.html` is regenerated as a hub
listing all of them (with release/review counts per entry). Alongside each page
sit `.metrics.json` and `.meta.json` sidecars — the aggregated numbers that both
the charts and the hub are built from.

Navigation between pages is injected automatically on every run, so an older
page also links forward to newer ones:

- **← 履歴一覧** back to the hub
- **前の/次の週次・日次** the neighbouring page of the same kind
- on a weekly page, **この期間の日次ブリーフ** — one chip per daily brief inside
  that week's window (the drill-down path for a meeting question)
- on a daily page, **この日を含む週次サマリ**

### Changing or adding repositories

Just edit the `REPOS` array in `config.local.sh` — the daily/weekly briefs group
their output per repository automatically. No code changes needed when you move
teams or take on more repos.

## Privacy

Repo names, webhook URLs and any other specifics live only in the gitignored
`config.local.sh`. Generated HTML and logs are written to `OUTPUT_DIR` outside
the repository. The committed tree contains no private data — safe to publish.

## Scheduling details

`scripts/install.sh` generates launchd plists from your config into
`~/Library/LaunchAgents/`. launchd GUI jobs run with a minimal `PATH`, so the
generated jobs set `PATH` to common Homebrew/system locations; if `claude`,
`gh`, or `python3` live elsewhere, adjust `GB_PATH_ENV` in `scripts/install.sh`.

Uninstall:

```bash
./scripts/uninstall.sh
```

## Extending

Add a new automation under `commands/<name>/` and it's instantly available as
`github-brief <name>`. Full walkthrough and the helper API:
[docs/ADDING_A_COMMAND.md](docs/ADDING_A_COMMAND.md).

## Notes

Built on the current Claude Code CLI. Flags used: `-p`, `--allowedTools`,
`--permission-mode`, `--add-dir`, `--max-turns`, `--model`, `--output-format`.
If a flag differs in your version, check `claude --help`.

## License

[MIT](LICENSE)
