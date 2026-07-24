# github-brief

[English](README.md) | **日本語**

GitHub リポジトリの活動を自動で要約し、Slack とローカル HTML ページに届ける
ツールです。[Claude Code](https://claude.com/product/claude-code) と
[GitHub CLI](https://cli.github.com/) を使って自分のマシン上で完結して動作します —
サードパーティのサーバーもコネクタも不要で、自分で送ると決めた Slack メッセージ
以外のデータがラップトップの外に出ることはありません。

最初に同梱されている自動化は **pr-brief** です:

- **デイリー(平日朝):** 自分のレビュー待ちの PR と、前日以降にベースブランチへ
  マージされた PR を、それぞれ変更内容の1行サマリー付きで届けます。
- **ウィークリー(例: 金曜):** 過去1週間にリリースされたもの・新規オープンされた
  ものすべてを、進捗報告にそのまま貼れる自動生成ハイライト付きでまとめます。

**単一・複数どちらのリポジトリ**にも対応しており、小さなハーネスとして構築されて
いるため、活動系の自動化を後から追加していけます
([docs/ADDING_A_COMMAND.ja.md](docs/ADDING_A_COMMAND.ja.md) 参照)。

> なぜ1本のスクリプトではなくハーネスなのか?
> [docs/ARCHITECTURE.ja.md](docs/ARCHITECTURE.ja.md) を参照してください。
> 要約すると: 決定的な処理(日付計算、`gh` クエリ、Slack 投稿)はシェルに残し、
> 要約と HTML レンダリングだけを、読み取り専用・コスト上限付きの厳格な設定の下で
> モデルに委譲します。

## 必要なもの

- macOS(スケジューリングに `launchd` を使用。コマンド自体はポータブル)
- `python3`(macOS Command Line Tools に同梱)
- [`gh`](https://cli.github.com/) の認証済み環境: `gh auth login`
- Claude Code CLI のインストールとログイン(`claude` が実行可能なこと)
- Slack の [Incoming Webhook](https://api.slack.com/messaging/webhooks) URL(任意)

## クイックスタート

```bash
git clone https://github.com/otajisan/github-brief.git
cd github-brief
cp config.example.sh config.local.sh
$EDITOR config.local.sh          # REPOS と SLACK_WEBHOOK_URL を設定

chmod +x bin/github-brief scripts/*.sh

# まず一度手動で実行
./bin/github-brief pr-brief daily
./bin/github-brief pr-brief weekly

# HTML を確認
./scripts/serve.sh               # http://localhost:8787/index.html

# スケジュール登録(デフォルト: 平日 09:00 デイリー、金曜 10:30 ウィークリー)
./scripts/install.sh
```

スケジュール済みジョブを即時実行してテストするには:

```bash
launchctl kickstart -k gui/$(id -u)/com.github-brief.daily
```

## 設定

環境固有の値はすべて `config.local.sh`(gitignore 済み)に置きます。主な設定:

| 設定 | 意味 |
|---|---|
| `REPOS` | 対象の `owner/repo` を並べた Bash 配列(1つでも複数でも可) |
| `BASE_BRANCH` | マージされたら「リリース済み」と数えるブランチ(`main`) |
| `REVIEW_FILTER` | `review-requested:@me` または `team-review-requested:ORG/TEAM` |
| `SLACK_WEBHOOK_URL` | Incoming Webhook。空なら HTML のみ |
| `OUTPUT_DIR` | HTML / ログの出力先(リポジトリ外) |
| `MODEL` / `MAX_TURNS` | 使用モデルと1実行あたりのコスト上限 |
| `TZ_OFFSET_HOURS` | 集計ウィンドウのタイムゾーン(JST = 9) |
| `DAILY_*` / `WEEKLY_*` | スケジュールとウィークリーの集計範囲 |

### リポジトリの変更・追加

`config.local.sh` の `REPOS` 配列を編集するだけです — デイリー/ウィークリーの
ブリーフは自動的にリポジトリごとに出力をグループ化します。チーム異動や担当
リポジトリの追加でコード変更は不要です。

## プライバシー

リポジトリ名・Webhook URL などの固有情報は gitignore 済みの `config.local.sh`
にのみ存在します。生成された HTML とログはリポジトリ外の `OUTPUT_DIR` に書き
出されます。コミットされるツリーには私的なデータが一切含まれないため、安全に
公開できます。

## スケジューリングの詳細

`scripts/install.sh` は設定から launchd の plist を生成して
`~/Library/LaunchAgents/` に配置します。launchd の GUI ジョブは最小限の `PATH`
で動くため、生成されるジョブは一般的な Homebrew / システムのパスを `PATH` に
設定します。`claude`・`gh`・`python3` が別の場所にある場合は
`scripts/install.sh` の `GB_PATH_ENV` を調整してください。

アンインストール:

```bash
./scripts/uninstall.sh
```

## 拡張

`commands/<name>/` の下に新しい自動化を追加すると、そのまま
`github-brief <name>` として実行可能になります。手順とヘルパー API の詳細:
[docs/ADDING_A_COMMAND.ja.md](docs/ADDING_A_COMMAND.ja.md)。

## 備考

現行の Claude Code CLI を前提に構築されています。使用しているフラグ: `-p`,
`--allowedTools`, `--permission-mode`, `--add-dir`, `--max-turns`, `--model`,
`--output-format`。お使いのバージョンでフラグが異なる場合は `claude --help` を
確認してください。

## ライセンス

[MIT](LICENSE)
