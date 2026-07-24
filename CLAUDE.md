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
| `pr-brief` | `weekly` | Weekly release / newly-opened summary with highlights |

## Design principles (rules to preserve)

1. **Heartbeat loop.** launchd wakes a command on a schedule; it gathers data,
   produces output, and exits. Nothing runs resident.
2. **Deterministic vs fuzzy split.** Breakable logic — date-window math, `gh`
   search queries, file I/O, Slack posting — lives in shell
   (`lib/common.sh`). Only fuzzy work (per-PR summaries, HTML rendering) is
   delegated to Claude via prompt templates. Never move date/JSON/query logic
   into a prompt; never move summarization into shell.
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
lib/common.sh             # shared deterministic helpers (gb::*): config, windows, claude runner, slack
commands/<name>/
  command.sh              # orchestration for one automation (deterministic shell)
  prompts/*.md            # the fuzzy instructions handed to Claude (@@KEY@@ placeholders)
scripts/
  install.sh              # generate + bootstrap launchd jobs from config
  uninstall.sh            # bootout + remove plists
  gen_plists.py           # plist builder; JOBS dict maps label -> (args, schedule)
  serve.sh                # serve OUTPUT_DIR at http://localhost:PORT/index.html
config.example.sh         # committed template (placeholders only)
config.local.sh           # gitignored real config — never read values from it into committed files
docs/                     # ARCHITECTURE.md, ADDING_A_COMMAND.md
```

## Common commands

```bash
# Run manually
./bin/github-brief pr-brief daily
./bin/github-brief pr-brief weekly

# View generated HTML
./scripts/serve.sh                # http://localhost:8787/index.html (port = SERVE_PORT or $1)

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
   `GB_LOG`, compute output paths under `$OUTPUT_DIR`, render the prompt with
   `gb::render`, run `gb::run_claude`, then `gb::update_index` +
   `gb::post_slack`; on failure `gb::notify_failure` and exit 1.
3. To schedule it, add an entry to `JOBS` in `scripts/gen_plists.py` and
   re-run `scripts/install.sh`.

Available helpers (`lib/common.sh`):

| Function | Purpose |
|---|---|
| `gb::load_config` | Source `config.local.sh`, ensure `OUTPUT_DIR` exists |
| `gb::log "msg"` | Timestamped log to `$GB_LOG` (stderr) |
| `gb::repos_lines` | Print configured repos, one per line |
| `gb::iso_window daily\|weekly` | Deterministic `SINCE UNTIL` (ISO8601 + tz offset) |
| `gb::render tpl KEY=VAL…` | Replace `@@KEY@@` placeholders in a prompt template |
| `gb::run_claude "prompt"` | Headless Claude run (read-only gh + Write, bounded) |
| `gb::update_index html` | Copy an HTML file to `index.html` |
| `gb::post_slack txt` | Post a text file to the Slack webhook (no-op if unset) |
| `gb::notify_failure "msg"` | Send a warning to Slack |

Prompt conventions: human-facing output (HTML/Slack) is written in Japanese;
prompts instruct Claude to create exactly the expected output files and
nothing else, and to stay read-only (`gh pr list` / `gh pr view` only).

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
- Delegate date-window computation, JSON handling, or `gh` query construction
  to the LLM — that logic belongs in shell/python3.
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
