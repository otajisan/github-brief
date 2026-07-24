# コントリビューション

[English](CONTRIBUTING.md) | **日本語**

github-brief の改善に興味を持っていただきありがとうございます。

## セットアップ

```bash
cp config.example.sh config.local.sh   # 自分のリポジトリ/Webhook を設定(gitignore 済み)
chmod +x bin/github-brief scripts/*.sh
./bin/github-brief pr-brief daily
```

## ガイドライン

- **`config.local.sh` と `OUTPUT_DIR` 配下は絶対にコミットしない。** gitignore
  されています — その状態を維持してください。実在のリポジトリ名・Webhook URL・
  メンバー名をコミット対象のファイルに書かないこと。
- **責務の分離を守る。** 決定的なロジック(日付、`gh` クエリ、配信)は
  `lib/common.sh` か各コマンドの `command.sh` に置きます。Claude のプロンプトに
  入れてよいのは要約・レンダリングだけです。
- **デフォルトは読み取り専用のまま。** 明確な理由なく `--allowedTools` の
  許可リストを広げないこと。GitHub への書き込み権限は決して与えないこと。
- **新しい自動化**は `commands/<name>/` 配下に追加します —
  [docs/ADDING_A_COMMAND.ja.md](docs/ADDING_A_COMMAND.ja.md) を参照。ロジックを
  複製せず `gb::*` ヘルパーを再利用してください。
- シェルは `bash`(macOS デフォルト)を対象とします。日付・JSON 処理は
  macOS/Linux 間のポータビリティのため `python3` を推奨します。
- 提出前にスクリプトへ [`shellcheck`](https://www.shellcheck.net/) を実行して
  ください。

## プルリクエスト

PR は焦点を絞り、何をなぜ変えるのかを記述してください。新しい設定キーを追加した
場合はその旨を明記してください(`config.example.sh` に安全なプレースホルダーで
追加し、README にも記載します)。
