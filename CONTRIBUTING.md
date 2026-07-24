# Contributing

Thanks for your interest in improving github-brief.

## Getting set up

```bash
cp config.example.sh config.local.sh   # your own repos/webhook (gitignored)
chmod +x bin/github-brief scripts/*.sh
./bin/github-brief pr-brief daily
```

## Guidelines

- **Never commit `config.local.sh`** or anything under `OUTPUT_DIR`. It's
  gitignored — keep it that way. No real repo names, webhook URLs, or member
  names in committed files.
- **Keep the split.** Deterministic logic (dates, `gh` queries, delivery) goes
  in `lib/common.sh` or a command's `command.sh`. Only summarization/rendering
  belongs in the Claude prompt.
- **Stay read-only by default.** Don't widen the `--allowedTools` allowlist
  without a clear reason; never grant write access to GitHub.
- **New automations** go under `commands/<name>/` — see
  [docs/ADDING_A_COMMAND.md](docs/ADDING_A_COMMAND.md). Reuse the `gb::*`
  helpers rather than duplicating logic.
- Shell targets `bash` (macOS default). Prefer `python3` for date/JSON work to
  stay portable across macOS/Linux.
- Run [`shellcheck`](https://www.shellcheck.net/) on scripts before submitting.

## Pull requests

Keep PRs focused, describe what changes and why, and note any new config keys
(add them to `config.example.sh` with safe placeholders and document in README).
