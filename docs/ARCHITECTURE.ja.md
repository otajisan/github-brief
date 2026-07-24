# アーキテクチャ

[English](ARCHITECTURE.md) | **日本語**

`github-brief` は GitHub リポジトリの活動要約を自動化するための、小さく拡張可能
なハーネスです。最初に同梱されている自動化は `pr-brief` ですが、新しい自動化を
追加式で足していける構造になっています。

## 設計原則: ループエンジニアリング

各自動化は **Heartbeat ループ**です: launchd がスケジュールに従って起動し、
データを収集し、出力を生成して終了します。1回の実行の中で、責務を意図的に
分割しています:

- **決定的な処理はシェルに残す。** 時間ウィンドウの計算、`gh` の検索クエリ、
  ファイルの書き出し・配信、Slack への投稿は、正確で再現可能でなければならない
  固定ロジックです。これらは `lib/common.sh` にあります。
- **曖昧な処理は Claude に委譲する。**「この PR は何を変えるのか」の要約と、
  読みやすい HTML ページのレンダリングだけがモデルに渡されるステップです。
- **実行の上限。** すべての Claude 実行は `--max-turns`(設定 `MAX_TURNS`)で
  上限が設けられ、コストを抑え、暴走ループを防ぎます。
- **シークレットの隔離。** Slack の Webhook URL はモデルのプロンプトに決して
  含めません。投稿するのはシェルだけです。
- **読み取り専用。** エージェントに許可されるのは `Bash(gh:*),Read,Write` のみ。
  マージ・クローズ・コメントはできません。

## レイアウト

```
github-brief/
├── bin/github-brief         # エントリポイント: commands/<name>/command.sh へディスパッチ
├── lib/common.sh            # 共有 gb::* ヘルパー(設定、ウィンドウ、claude、slack)
├── commands/                # 自動化ごとに1ディレクトリ(プラグイン風)
│   └── pr-brief/
│       ├── command.sh       # 実装: github-brief pr-brief {daily|weekly}
│       └── prompts/         # Claude に渡す「曖昧な」指示
│           ├── daily.md
│           └── weekly.md
├── scripts/
│   ├── install.sh           # 設定から launchd ジョブを生成・登録
│   ├── uninstall.sh
│   ├── gen_plists.py        # plist ビルダー(新コマンドのスケジュールは JOBS を拡張)
│   └── serve.sh             # http://localhost:PORT/index.html
├── config.example.sh        # コミットされるテンプレート(config.local.sh にコピー)
├── docs/
└── LICENSE
```

## データフロー(1実行あたり)

```
launchd ──> bin/github-brief <command> <mode>
                │
                ▼
        commands/<command>/command.sh
                │  gb::load_config        (config.local.sh)
                │  gb::iso_window <mode>   (決定的な SINCE..UNTIL)
                │  gb::render prompt       (@@KEY@@ 置換、REPOS を含む)
                ▼
        gb::run_claude ─────────────────────────────► Claude Code (ヘッドレス)
                                                        ├─ gh pr list (リポジトリごと)
                                                        ├─ 各 PR を要約
                                                        └─ HTML + Slack 本文を Write
                │
                │  gb::update_index  (HTML を index.html にコピー)
                │  gb::post_slack    (シェルのみ; Webhook はプロンプトに出さない)
                ▼
        out/ : *.html, index.html, slack-*.txt, logs/
```

## 設定とプライバシー

環境固有の値(リポジトリ名、Webhook URL、スケジュール、タイムゾーン、出力先)は
すべて **gitignore 済み**の `config.local.sh` に置かれます。コミットされるのは
プレースホルダーだけの `config.example.sh` です。生成された HTML / ログは
リポジトリ外の `OUTPUT_DIR`(デフォルト `~/.local/share/github-brief`)に書き
出されるため、私的なものがコミット対象になることはありません。
