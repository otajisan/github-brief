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
  aggregating the JSON, every number that appears in the output, the chart
  markup, writing/serving files, and posting to Slack are all fixed logic that
  must be correct and reproducible. These live in `lib/common.sh` and the
  `lib/*.py` helpers it calls.
- **Fuzzy work is delegated to Claude.** Summarizing "what a PR changes",
  grouping the week into highlights, and writing the page around the
  pre-rendered blocks are the only steps handed to the model. It is given an
  already-fetched JSON bundle, so it never queries GitHub for lists and never
  counts anything itself.
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
├── lib/
│   ├── common.sh            # shared gb::* helpers (config, windows, gh, claude, slack)
│   ├── collect_prs.py       # gh JSON -> bundle + metrics + .meta.json (all the numbers)
│   ├── render_charts.py     # metrics -> KPI/chart HTML fragment (CSS marks, self-contained)
│   └── build_site.py        # index.html history hub · nav injection · chart splicing
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
                │  gb::load_config         (config.local.sh)
                │  gb::iso_window <mode>    (deterministic SINCE..UNTIL)
                │  gb::fetch_prs  × repo    (gh pr list --json, queries stay in shell)
                │  gb::collect_prs          (bundle.json + metrics.json + .meta.json)
                │  gb::render_charts        (weekly: KPI + chart fragment)
                │  gb::render prompt        (@@KEY@@ substitution, incl. bundle path)
                ▼
        gb::run_claude ─────────────────────────────► Claude Code (headless)
                                                        ├─ Read bundle.json
                                                        ├─ summarize each PR
                                                        └─ Write HTML + Slack body
                │
                │  gb::inject_charts   (splice the chart block at <!-- gb:charts -->)
                │  gb::rebuild_site    (index.html hub + nav on every archived page)
                │  gb::post_slack      (shell-only; webhook stays out of prompt)
                ▼
        OUTPUT_DIR/
          pr-brief-<mode>-<YYYYMMDD>.html        the brief (archived, never overwritten)
          pr-brief-<mode>-<YYYYMMDD>.meta.json   window + counts, read by the hub
          pr-brief-<mode>-<YYYYMMDD>.metrics.json aggregates (also the 前期比 baseline)
          pr-brief-<mode>-<YYYYMMDD>.bundle.json the PR data handed to the model
          index.html                             regenerated history hub
          slack-*.txt, logs/
```

## Why the numbers and charts are pre-rendered

An LLM asked to both summarize and total up a list will occasionally do the
arithmetic wrong, and a chart it draws by hand can misstate a value while still
looking plausible. So counts, per-day buckets, the type breakdown and the chart
markup are computed in `lib/collect_prs.py` / `lib/render_charts.py`, and the
prompt is told to treat them as authoritative. The model's remaining job —
saying what a PR changes — is the part it is actually good at.

## Configuration & privacy

All environment-specific values (repo names, webhook URL, schedule, timezone,
output location) live in `config.local.sh`, which is **gitignored**. Only
`config.example.sh` with placeholders is committed. Generated HTML/logs are
written to `OUTPUT_DIR` (default `~/.local/share/github-brief`), outside the
repository, so nothing private is ever staged for commit.
