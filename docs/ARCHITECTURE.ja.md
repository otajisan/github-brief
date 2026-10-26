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
  JSON の集計、出力に現れるすべての数値、グラフのマークアップ、ファイルの
  書き出し・配信、Slack への投稿は、正確で再現可能でなければならない固定
  ロジックです。これらは `lib/common.sh` と、そこから呼ばれる `lib/*.py` に
  あります。
- **曖昧な処理は Claude に委譲する。**「この PR は何を変えるのか」の要約、
  週をハイライトへまとめる作業、事前生成ブロックの周りのページ生成だけが
  モデルに渡されるステップです。モデルには取得済みの JSON バンドルを渡すので、
  一覧のために GitHub へ問い合わせることはなく、自分で数を数えることもありません。
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
├── lib/
│   ├── common.sh            # 共有 gb::* ヘルパー(設定、ウィンドウ、gh、claude、slack)
│   ├── collect_prs.py       # gh JSON -> bundle + metrics + .meta.json(すべての数値)
│   ├── render_charts.py     # metrics -> KPI/グラフ HTML 断片(CSS マーク、自己完結)
│   └── build_site.py        # index.html 履歴ハブ・ナビ注入・グラフ差し込み
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
│   └── serve.sh             # http://localhost:PORT/index.html (SERVE_AT_LOGIN=1 で常駐)
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
                │  gb::load_config         (config.local.sh)
                │  gb::iso_window <mode>    (決定的な SINCE..UNTIL)
                │  gb::fetch_prs  × repo    (gh pr list --json; クエリはシェル側)
                │  gb::collect_prs          (bundle.json + metrics.json + .meta.json)
                │  gb::render_charts        (weekly: KPI + グラフ断片)
                │  gb::render prompt        (@@KEY@@ 置換、バンドルのパスを含む)
                ▼
        gb::run_claude ─────────────────────────────► Claude Code (ヘッドレス)
                                                        ├─ bundle.json を Read
                                                        ├─ 各 PR を要約
                                                        └─ HTML + Slack 本文を Write
                │
                │  gb::inject_charts   (<!-- gb:charts --> にグラフブロックを差し込む)
                │  gb::rebuild_site    (index.html ハブ + 全アーカイブのナビ更新)
                │  gb::post_slack      (シェルのみ; Webhook はプロンプトに出さない)
                ▼
        OUTPUT_DIR/
          pr-brief-<mode>-<YYYYMMDD>.html        ブリーフ本体(アーカイブ; 上書きしない)
          pr-brief-<mode>-<YYYYMMDD>.meta.json   ウィンドウ + 件数(ハブが読む)
          pr-brief-<mode>-<YYYYMMDD>.metrics.json 集計値(前期比の基準にもなる)
          pr-brief-<mode>-<YYYYMMDD>.bundle.json モデルに渡す PR データ
          index.html                             再生成される履歴ハブ
          slack-*.txt, logs/
```

## 数値とグラフを事前生成する理由

要約と集計を同時に頼むと、LLM はときどき計算を間違えます。手で描いたグラフは、
もっともらしく見えたまま値を誤って表現してしまうこともあります。そのため件数・
日別バケット・種別内訳・グラフのマークアップは `lib/collect_prs.py` /
`lib/render_charts.py` で計算し、プロンプトにはそれを正解として扱わせています。
モデルに残る仕事は「その PR が何を変えるのか」を書くこと — 本当に得意な部分だけです。

## 設定とプライバシー

環境固有の値(リポジトリ名、Webhook URL、スケジュール、タイムゾーン、出力先)は
すべて **gitignore 済み**の `config.local.sh` に置かれます。コミットされるのは
プレースホルダーだけの `config.example.sh` です。生成された HTML / ログは
リポジトリ外の `OUTPUT_DIR`(デフォルト `~/.local/share/github-brief`)に書き
出されるため、私的なものがコミット対象になることはありません。
