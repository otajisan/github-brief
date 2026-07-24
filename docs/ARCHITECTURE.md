# Architecture

**English** | [日本語](ARCHITECTURE.ja.md)

`github-brief` is a small, extensible harness for automating summaries of
GitHub repository activity. The first bundled automation is `pr-brief`, but the
structure is designed so that new automations are additive.

## Design principle: loop engineering

Each automation is a **Heartbeat loop**: launchd wakes it on a schedule, it
gathers data, produces output, and exits. Within a run we deliberately split
responsibilities:

- **Deterministic work stays in shell.** Time-window math, `gh` search queries,
  writing/serving files, and posting to Slack are all fixed logic that must be
  correct and reproducible. These live in `lib/common.sh`.
- **Fuzzy work is delegated to Claude.** Summarizing "what a PR changes" and
  rendering a readable HTML page are the only steps handed to the model.
- **Bounded Execution.** Every Claude run is capped by `--max-turns` (config
  `MAX_TURNS`) to bound cost and prevent runaway loops.
- **Secret isolation.** The Slack webhook URL is never placed in the model
  prompt; only the shell posts to it.
- **Read-only.** The agent is granted only `Bash(gh:*),Read,Write`; it cannot
  merge, close, or comment.

## Layout

```
github-brief/
├── bin/github-brief         # entrypoint: dispatches to commands/<name>/command.sh
├── lib/common.sh            # shared gb::* helpers (config, windows, claude, slack)
├── commands/                # one directory per automation (plugin-like)
│   └── pr-brief/
│       ├── command.sh       # implements: github-brief pr-brief {daily|weekly}
│       └── prompts/         # the "fuzzy" instructions handed to Claude
│           ├── daily.md
│           └── weekly.md
├── scripts/
│   ├── install.sh           # generate + load launchd jobs from config
│   ├── uninstall.sh
│   ├── gen_plists.py         # builds plists (extend JOBS to schedule new commands)
│   └── serve.sh             # http://localhost:PORT/index.html
├── config.example.sh        # committed template (copy to config.local.sh)
├── docs/
└── LICENSE
```

## Data flow (per run)

```
launchd ──> bin/github-brief <command> <mode>
                │
                ▼
        commands/<command>/command.sh
                │  gb::load_config        (config.local.sh)
                │  gb::iso_window <mode>   (deterministic SINCE..UNTIL)
                │  gb::render prompt       (@@KEY@@ substitution, incl. REPOS)
                ▼
        gb::run_claude ─────────────────────────────► Claude Code (headless)
                                                        ├─ gh pr list (per repo)
                                                        ├─ summarize each PR
                                                        └─ Write HTML + Slack body
                │
                │  gb::update_index  (copy HTML -> index.html)
                │  gb::post_slack    (shell-only; webhook stays out of prompt)
                ▼
        out/ : *.html, index.html, slack-*.txt, logs/
```

## Configuration & privacy

All environment-specific values (repo names, webhook URL, schedule, timezone,
output location) live in `config.local.sh`, which is **gitignored**. Only
`config.example.sh` with placeholders is committed. Generated HTML/logs are
written to `OUTPUT_DIR` (default `~/.local/share/github-brief`), outside the
repository, so nothing private is ever staged for commit.
