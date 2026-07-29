# 新しいコマンドの追加

[English](ADDING_A_COMMAND.md) | **日本語**

「コマンド」とは `commands/<name>/` 配下の自己完結した自動化のことです。追加に
あたって `bin/github-brief` や既存コマンドの編集は一切不要です。

このハーネスに向いているアイデア: `stale-prs`(N日以上停滞している PR)、
`review-latency`(初回レビューまでの時間の統計)、`release-notes`(マージ済み
PR からのノート草案)、`issue-triage`、`deploy-digest` など。

## 1. コマンドディレクトリを作る

```
commands/stale-prs/
├── command.sh
└── prompts/            # 任意。レンダリングを Claude に委譲する場合のみ
    └── default.md
```

## 2. `command.sh` を書く

共有ライブラリを使います。最小のスケルトン:

```bash
#!/usr/bin/env bash
set -euo pipefail
CMD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GB_ROOT="$(cd "$CMD_DIR/../.." && pwd)"
# shellcheck source=/dev/null
source "$GB_ROOT/lib/common.sh"
gb::load_config

export GB_LOG="$OUTPUT_DIR/logs/stale-prs-$(date +%Y%m%d-%H%M%S).log"
gb::guard_runtime          # ハングは静かに詰まらせず、明示的に失敗させる

HTML_OUT="$OUTPUT_DIR/stale-prs-$(date +%Y%m%d).html"
SLACK_TXT="$OUTPUT_DIR/slack-stale-prs-$(date +%Y%m%d).txt"

PROMPT="$(gb::render "$CMD_DIR/prompts/default.md" \
  "REPOS=$(gb::repos_lines)" "HTML_OUT=$HTML_OUT" "SLACK_TXT=$SLACK_TXT" "PORT=$SERVE_PORT")"

if gb::run_claude "$PROMPT" >>"$GB_LOG" 2>&1; then
  gb::rebuild_site            # index.html ハブ + 全アーカイブのナビを再生成
  gb::post_slack "$SLACK_TXT"
else
  gb::notify_failure "github-brief stale-prs failed. log: $GB_LOG"
  exit 1
fi
```

これだけで即座に実行可能になります:

```bash
github-brief stale-prs
```

## 利用できるヘルパー(`lib/common.sh`)

| 関数 | 用途 |
|---|---|
| `gb::load_config` | `config.local.sh` を読み込み、`OUTPUT_DIR` の存在を保証 |
| `gb::log "msg"` | `$GB_LOG` へのタイムスタンプ付きログ(stderr) |
| `gb::guard_runtime [秒]` | 見張り: ハングした実行を停止し Slack へ警告(`RUN_TIMEOUT_SECONDS`) |
| `gb::repos_lines` | 設定済みリポジトリを1行1件で出力 |
| `gb::iso_window daily\|weekly` | 決定的な `SINCE UNTIL`(ISO8601 + タイムゾーン) |
| `gb::window_label since until` | 人間向けの期間表記(`2026/07/22 14:30 〜 07/29 10:30`) |
| `gb::fetch_prs repo out.json …` | `gh pr list --json …` のダンプ(追加引数はそのまま渡る) |
| `gb::collect_prs …` | ダンプを統合 → `bundle.json` + `metrics.json` + `.meta.json` |
| `gb::render_charts metrics out` | KPI + グラフ断片を事前生成 |
| `gb::prev_metrics mode current` | 直前の metrics ファイル(前期比の基準) |
| `gb::render tpl KEY=VAL…` | プロンプトテンプレート内の `@@KEY@@` を置換 |
| `gb::run_claude "prompt"` | ヘッドレス Claude 実行(読み取り専用 gh + Write、上限付き) |
| `gb::inject_charts html frag` | `<!-- gb:charts -->` にグラフブロックを差し込む |
| `gb::rebuild_site` | `index.html` ハブとアーカイブ各ページのナビを再生成 |
| `gb::post_slack txt` | テキストファイルを Slack Webhook に投稿(未設定なら no-op) |
| `gb::notify_failure "msg"` | Slack に警告を送信 |

### 履歴ハブに載せる

`lib/build_site.py` が索引化するのは、現在は
`pr-brief-<daily|weekly>-<YYYYMMDD>.html` という名前のページと、その隣に置かれた
`<同じステム>.meta.json`(`gb::collect_prs --out-meta` が書き出す)です。新しい
コマンドのページをハブに載せるには `lib/build_site.py` の `NAME_RE` / `MODE_JA` を
拡張してください。それまでは自前の Slack 本文からページへリンクします。1実行=1
ファイルでアーカイブし、前日のページを上書きしないこと。

## 3.(任意)スケジュールに載せる

`scripts/gen_plists.py` の `JOBS` にエントリを追加し、`scripts/install.sh` を
再実行します:

```python
JOBS = {
    ...,
    "com.github-brief.stale-prs": (["stale-prs"], {"Weekday": 1, "Hour": 9, "Minute": 30}),
}
```

## 規約

- 人が読む出力はチームで使っている言語で。プロンプトは明示的に書くこと。
- 強い理由がない限り読み取り専用を維持し、`--allowedTools` の許可リストは
  最小限に保つこと。
- 出力は `OUTPUT_DIR` に書き、リポジトリ内には決して書かないこと。
