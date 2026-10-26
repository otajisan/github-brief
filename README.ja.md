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
  さらにリリース週のグラフ(日別リリース数・種別内訳・リポジトリ別・作者別)と
  前期比も表示します。

各実行の結果はすべてアーカイブされ、`index.html` は**履歴ハブ**になります —
最新のウィークリー/デイリーを先頭に置き、その下に全アーカイブを並べます。各ページ
にはナビゲーションが入るので、定例MTGではウィークリーサマリを開き、詳細を聞かれた
らその週のデイリーブリーフへそのまま飛べます。

**単一・複数どちらのリポジトリ**にも対応しており、小さなハーネスとして構築されて
いるため、活動系の自動化を後から追加していけます
([docs/ADDING_A_COMMAND.ja.md](docs/ADDING_A_COMMAND.ja.md) 参照)。

> なぜ1本のスクリプトではなくハーネスなのか?
> [docs/ARCHITECTURE.ja.md](docs/ARCHITECTURE.ja.md) を参照してください。
> 要約すると: 決定的な処理(日付計算、`gh` クエリ、集計、出力に出るすべての数値、
> グラフ、Slack 投稿)はシェルに残し、要約と周辺ページの生成だけを、読み取り専用・
> コスト上限付きの厳格な設定の下でモデルに委譲します。

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

# HTML を確認(index.html = 履歴ハブ: 最新＋アーカイブ)
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
| `SERVE_PORT` / `SERVE_AT_LOGIN` | 履歴ハブのポート。`1` ならログイン時から常駐させる(既定 `0`、後述) |
| `MODEL` / `MAX_TURNS` | 使用モデルと1実行あたりのコスト上限 |
| `RUN_TIMEOUT_SECONDS` | 実時間の上限。ハングした実行を停止し Slack へ警告(既定 3600) |
| `TZ_OFFSET_HOURS` | 集計ウィンドウのタイムゾーン(JST = 9) |
| `DAILY_*` / `WEEKLY_*` | スケジュールとウィークリーの集計範囲 |
| `GH_LIMIT` | `gh` クエリ1回あたりの最大取得件数(既定 200) |
| `BODY_MAX_CHARS` | モデルに渡す前に PR 本文を切り詰める文字数(既定 1200) |
| `NETWORK_WAIT_SECONDS` | `api.github.com` の応答を待つ上限。超えたら実行を中止(既定 180) |
| `GH_RETRIES` | `gh` クエリ1回あたりの試行回数。使い切ると実行を失敗させる(既定 3) |

## 履歴を辿る

`OUTPUT_DIR` には実行ごとに `pr-brief-<mode>-<YYYYMMDD>.html` が1ページずつ
たまり、`index.html` はそれらを一覧するハブとして毎回再生成されます(各エントリに
リリース件数・レビュー待ち件数のバッジ付き)。各ページの隣には `.metrics.json` と
`.meta.json` が並び、グラフとハブはどちらもこの集計値から作られます。

ページ間のナビゲーションは毎回自動で注入されるため、古いページからも新しいページへ
リンクが張られます:

- **← 履歴一覧** ハブへ戻る
- **前の/次の週次・日次** 同じ種類の隣のページ
- ウィークリーのページには **この期間の日次ブリーフ** — その週のウィンドウに入る
  デイリーブリーフをチップで列挙(MTGで詳細を聞かれたときの掘り下げ経路)
- デイリーのページには **この日を含む週次サマリ**

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

`SERVE_AT_LOGIN="1"` のとき、install は `com.github-brief.serve` も登録します。
ログイン時に `scripts/serve.sh` を起動し、終了しても再起動するので、再起動後も
`http://localhost:SERVE_PORT/` をそのまま開けます。`0` にして `install.sh` を
再実行すると登録が外れます。`serve.sh`(手動で起動した場合も)は `lib/serve.py`
を動かします。待ち受けは `127.0.0.1` のみで、`Host` が `localhost` /
`127.0.0.1` 以外のリクエストは拒否し、配信するのは `*.html` のページだけです
(`logs/` と JSON のサイドカーは 404)。スクリプトと外部への通信を禁止する CSP
も付けます。

Slack Webhook が投稿を拒否した場合(URL の失効、メッセージ過大など)は、
`slack: send failed (HTTP <code>: <理由>)` をログに残して警告を送り、ページを
書き出したあとで exit 1 します。警告自体が届かない場合でも、launchd 上で失敗
したジョブとして見えます。

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
