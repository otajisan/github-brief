# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Overview

github-brief is an automation harness that summarizes GitHub repository
activity and delivers it to Slack and a local HTML page. It runs entirely on
the user's machine via launchd + the `gh` CLI + headless Claude Code. The
design philosophy is **loop engineering**: instead of polishing prompts, we
engineer the loop that drives the agent — trigger, inputs, stop conditions,
and outputs.

Current commands:

| Command | Modes | What it does |
|---|---|---|
| `pr-brief` | `daily` | Review queue + PRs merged into the base branch since the previous day |
| `pr-brief` | `weekly` | Weekly release / newly-opened summary with highlights + charts |

Outputs per run (all under `$OUTPUT_DIR`): `pr-brief-<mode>-<YYYYMMDD>.html`
with `.bundle.json` / `.metrics.json` / `.meta.json` sidecars,
`slack-pr-brief-<mode>-<YYYYMMDD>.txt`, and a regenerated `index.html` history
hub. Weekly pages carry a pre-rendered KPI + chart block; every archived page
carries an injected nav bar (hub · prev/next of the same mode · weekly↔daily
cross links) so the weekly summary can be drilled down into the daily briefs.

## Design principles (rules to preserve)

1. **Heartbeat loop.** launchd wakes a command on a schedule; it gathers data,
   produces output, and exits. Nothing runs resident — the one exception is
   the opt-in `com.github-brief.serve` login item (`SERVE_AT_LOGIN=1`), a
   loopback-only static server for the history hub that does no work itself.
2. **Deterministic vs fuzzy split.** Breakable logic — date-window math, `gh`
   search queries, JSON aggregation, every number in the output, chart markup,
   file I/O, Slack posting — lives in shell (`lib/common.sh`) and the `lib/*.py`
   helpers it calls. Only fuzzy work (per-PR summaries, weekly highlights, the
   page around the pre-rendered blocks) is delegated to Claude via prompt
   templates. Never move date/JSON/query/arithmetic logic into a prompt; never
   move summarization into shell.
3. **Bounded execution.** Every Claude run is capped with `--max-turns`
   (config `MAX_TURNS`) to fix the per-run cost ceiling.
4. **Secret isolation.** `SLACK_WEBHOOK_URL` is never placed in a prompt or
   passed to the model. Only shell (`gb::post_slack`) posts to it.
5. **Read-only agent.** The allowlist is exactly
   `Bash(gh:*),Read,Write`. The agent must never merge, close, comment, or
   otherwise write to GitHub. Do not widen the allowlist.
6. **Plugin-style extension.** New automations are added as
   `commands/<name>/` only. Do not modify `bin/github-brief` or existing
   commands to add one. Reuse `gb::*` helpers instead of duplicating logic.
7. **Privacy.** Environment-specific values (repo names, webhook URL,
   schedule) live in gitignored `config.local.sh`; only `config.example.sh`
   with placeholders is committed. Generated HTML/logs go to `OUTPUT_DIR`
   (outside the repo). The committed tree must contain no private data.

## Layout & responsibilities

```
bin/github-brief          # dispatcher only — finds commands/<name>/command.sh; never add logic here
lib/common.sh             # shared deterministic helpers (gb::*): config, windows, gh, claude runner, slack
lib/collect_prs.py        # gh JSON -> bundle.json + metrics.json + .meta.json (all counts/buckets)
lib/render_charts.py      # metrics.json -> self-contained KPI + chart HTML fragment (CSS marks, no SVG)
lib/build_site.py         # index.html history hub · nav injection · chart splicing
commands/<name>/
  command.sh              # orchestration for one automation (deterministic shell)
  prompts/*.md            # the fuzzy instructions handed to Claude (@@KEY@@ placeholders)
scripts/
  install.sh              # generate + bootstrap launchd jobs from config
  uninstall.sh            # bootout + remove plists
  gen_plists.py           # plist builder; JOBS dict maps label -> (args, schedule)
  serve.sh                # serve OUTPUT_DIR at http://localhost:PORT/index.html (127.0.0.1)
config.example.sh         # committed template (placeholders only)
config.local.sh           # gitignored real config — never read values from it into committed files
docs/                     # ARCHITECTURE.md, ADDING_A_COMMAND.md
```

## Common commands

```bash
# Run manually
./bin/github-brief pr-brief daily
./bin/github-brief pr-brief weekly

# View generated HTML (index.html is the history hub: latest weekly/daily + archive)
./scripts/serve.sh                # http://localhost:8787/index.html (port = SERVE_PORT or $1)

# Rebuild the hub + nav without re-running a brief (e.g. after editing lib/build_site.py)
python3 lib/build_site.py nav   --output-dir "$OUTPUT_DIR"
python3 lib/build_site.py index --output-dir "$OUTPUT_DIR"

# Schedule / unschedule (macOS launchd)
./scripts/install.sh
./scripts/uninstall.sh

# Fire a scheduled job immediately (test)
launchctl kickstart -k gui/$(id -u)/com.github-brief.daily

# Logs land in $OUTPUT_DIR/logs/
```

## Adding a new command

Full walkthrough: `docs/ADDING_A_COMMAND.md`. Summary:

1. Create `commands/<name>/command.sh` (+ `prompts/*.md` if delegating
   rendering). It is immediately runnable as `github-brief <name>` — no
   dispatcher changes.
2. `command.sh` skeleton: source `lib/common.sh`, `gb::load_config`, set
   `GB_LOG` + `GB_FAILURE_CONTEXT`, arm `gb::guard_runtime` (a hang must fail
   loudly — an unbounded run keeps launchd's job in "running" state and silently
   skips every later schedule; the same call arms the EXIT trap so a *fast*
   death is just as loud), gate on `gb::wait_for_network` (launchd fires a
   missed job on wake, before Wi-Fi is back), compute output paths under
   `$OUTPUT_DIR`, fetch data with
   `gb::fetch_prs` + aggregate with `gb::collect_prs` (never in a prompt),
   render the prompt with `gb::render`, run `gb::run_claude`, then
   `gb::rebuild_site` + `gb::post_slack`; on failure `gb::notify_failure` and
   exit 1. Name the page `<name>-<mode>-<YYYYMMDD>.html` and write a matching
   `.meta.json` (via `gb::collect_prs --out-meta`) so it appears in the hub.
3. To schedule it, add an entry to `JOBS` in `scripts/gen_plists.py` and
   re-run `scripts/install.sh`.

Available helpers (`lib/common.sh`):

| Function | Purpose |
|---|---|
| `gb::load_config` | Source `config.local.sh`, ensure `OUTPUT_DIR` exists |
| `gb::log "msg"` | Timestamped log to `$GB_LOG` (stderr) |
| `gb::guard_runtime [sec]` | Watchdog: kill + Slack-warn a run that hangs (`RUN_TIMEOUT_SECONDS`); also arms the EXIT trap that Slack-warns any non-zero exit |
| `gb::wait_for_network [sec]` | Block until `api.github.com` answers (`NETWORK_WAIT_SECONDS`); 1 if it never does |
| `gb::repos_lines` | Print configured repos, one per line |
| `gb::iso_window daily\|weekly` | Deterministic `SINCE UNTIL` (ISO8601 + tz offset) |
| `gb::window_label since until` | Human-facing window (`2026/07/22 14:30 〜 07/29 10:30`) |
| `gb::fetch_prs repo out.json …` | `gh pr list --json …` dump (queries stay in shell); retried (`GH_RETRIES`), written atomically |
| `gb::collect_prs …` | Merge dumps → `bundle.json` + `metrics.json` + `.meta.json` |
| `gb::render_charts metrics out` | Pre-rendered KPI + chart fragment (weekly) |
| `gb::prev_metrics mode current` | Newest earlier metrics file, for the 前期比 delta |
| `gb::render tpl KEY=VAL…` | Replace `@@KEY@@` placeholders in a prompt template |
| `gb::run_claude "prompt"` | Headless Claude run (read-only gh + Write, bounded) |
| `gb::inject_charts html frag` | Splice the chart block into `<!-- gb:charts -->` |
| `gb::rebuild_site` | Rebuild `index.html` hub + refresh nav on every archived page |
| `gb::post_slack txt` | Post a text file to the Slack webhook (no-op if unset) |
| `gb::notify_failure "msg"` | Send a warning to Slack |

Prompt conventions: human-facing output (HTML/Slack) is written in Japanese;
prompts instruct Claude to create exactly the expected output files and
nothing else, and to stay read-only. Prompts receive a **pre-fetched bundle
path** and read it with `Read` — they must not run `gh pr list` (`gh pr view`
stays allowed as a rare fallback for an empty PR body). Totals come from the
`@@COUNTS@@` placeholder; the weekly page emits a bare `<!-- gb:charts -->`
line where the deterministic KPI/chart block is spliced in, and must not draw
its own charts or restate the numbers. Pages must be complete documents with a
`<body>` tag and no `position:fixed/sticky`, because `gb::rebuild_site` injects
a nav bar right after `<body>`.

## Claude Code invocation contract

`gb::run_claude` is the single place Claude is invoked:

```bash
claude -p "<prompt>" \
  --model "$MODEL" \
  --max-turns "$MAX_TURNS" \
  --allowedTools "Bash(gh:*),Read,Write" \
  --permission-mode acceptEdits \
  --add-dir "$OUTPUT_DIR" \
  --output-format json
```

Keep new commands on this helper rather than calling `claude` directly. Flag
names can differ across CLI versions — verify with `claude --help` if a flag
is rejected.

## Do NOT

- Commit `config.local.sh`, anything under `OUTPUT_DIR`/`out/`, `*.log`, or
  generated plists.
- Write real repository names, team/member names, or webhook URLs into any
  committed file (code, docs, examples, tests). Use placeholders like
  `owner/repo-a`.
- Perform or enable write operations against GitHub (`gh pr merge/close/
  comment`, etc.) from the agent.
- Widen the `--allowedTools` allowlist or relax `--max-turns` without a
  strong, documented reason.
- Delegate date-window computation, JSON handling, `gh` query construction,
  counting/percentages, or chart drawing to the LLM — that logic belongs in
  shell/python3 (`lib/collect_prs.py`, `lib/render_charts.py`).
- Hand-write `index.html`; it is generated by `lib/build_site.py index` on every
  run. Edit the generator, not the output.
- Write generated output into the repository tree; always target
  `$OUTPUT_DIR`.

## Coding conventions

- Shell targets `bash` (macOS default) with `set -euo pipefail`; functions
  namespaced `gb::*`.
- Use `python3` (not `date -d`/`jq`) for date and JSON work — portable across
  macOS/Linux (see `gb::iso_window`, `gb::post_slack`).
- Run `shellcheck` on all shell scripts before pushing.
- New config keys: add to `config.example.sh` with a safe placeholder,
  document in README, and validate presence in `gb::load_config` if required.

## Documentation languages

User-facing docs are bilingual: English is canonical (`README.md`,
`CONTRIBUTING.md`, `docs/*.md`), each with a Japanese counterpart (`*.ja.md`)
linked from a language-switcher line at the top. When editing any of these
docs, apply the same change to the other language version in the same commit.
`CLAUDE.md` and prompt templates are exempt (English / as-is).
