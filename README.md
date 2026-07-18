# CodexWork HumanBreak

[![CI](https://github.com/senbaph08/CodexWork-HumanBreak/actions/workflows/ci.yml/badge.svg)](https://github.com/senbaph08/CodexWork-HumanBreak/actions/workflows/ci.yml)
![macOS 13+](https://img.shields.io/badge/macOS-13%2B-111827?logo=apple)
![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)

Codex CLI / Codex App が作業している間、人間に「PCから離れて休みましょう」と促す macOS 用休憩アプリです。

プロンプト送信後に夕暮れラウンジ風の専用 Chrome ウィンドウを全画面表示し、穏やかなオリジナル音楽を再生します。Codex の作業完了時には画面を自動で閉じます。

## Features

- Codex CLI / Codex App 共通のライフサイクルフックで開始・終了を検知
- 「完了するまでPCから離れて、ゆっくり休みましょう」という休憩メッセージ
- 著作権上安全なWeb Audio生成の内蔵オリジナル曲
- 音楽と完了通知音の個別ON/OFF・音量設定
- 音楽OFF時だけ鳴る、柔らかな3音の完了チャイム
- MP3、M4A/AAC、WAV、OGG、FLACのプレイリスト
- 複数のCodexタスクを1つの休憩画面に集約
- 承認要求時には画面を閉じ、人間の操作後に自動再開
- ネイティブAppKit製のmacOSアプリとメニューバー常駐
- プロンプト本文やトランスクリプトを保存しないローカル完結設計

## Requirements

- macOS 13以降（開発・検証環境: macOS 15）
- Google Chrome
- Python 3.9以降
- Codex CLI または Codex App（ライフサイクルフック対応版）
- デスクトップアプリのビルドにはXcode Command Line Tools

## Quick start

### 1. バックエンドをインストール

```bash
git clone https://github.com/senbaph08/CodexWork-HumanBreak.git
cd CodexWork-HumanBreak
/usr/bin/python3 install.py
```

インストーラーは次をユーザー領域へ配置します。

- アプリ本体: `~/Library/Application Support/Codex Rest/`
- CLI: `~/.local/bin/codex-rest`
- Codexフック: `~/.codex/hooks.json`

既存の `hooks.json` は保持され、Codex Rest用の4イベントだけが追加されます。

### 2. Codexでフックを信頼

Codexを再起動し、Codex CLIで `/hooks` を開いて次の4件を確認・信頼します。

- `UserPromptSubmit`
- `Stop`
- `PermissionRequest`
- `PostToolUse`

### 3. デスクトップアプリをビルド・起動

```bash
/usr/bin/python3 build_macos_app.py --install
```

`~/Applications/Codex Rest.app` にAd-hoc署名済みアプリが配置されます。アプリを閉じてもメニューバーから設定を開けます。

## Commands

```bash
codex-rest settings   # ブラウザ設定画面を開く
codex-rest status     # タスク・画面・音声の状態を確認
codex-rest doctor     # Chrome、フック、通知音などを診断
codex-rest uninstall  # 本体と追加フックを削除（設定・音源は保持）
```

設定と音源も削除する場合:

```bash
codex-rest uninstall --purge-data
```

## How it works

```text
Codex CLI / App
    │ lifecycle hooks
    ▼
codex-rest hook client
    │ authenticated loopback HTTP
    ▼
local Python daemon ─── settings / playlist
    │
    ├── dedicated full-screen Chrome window
    └── macOS completion chime (afplay)
```

タスクは `session_id + turn_id` で識別します。同時に複数タスクが動いていても休憩画面は1つだけ開き、最後のタスクが終了したときに閉じます。

ローカルHTTPサーバーは `127.0.0.1` のみにバインドし、ランダムトークン、Origin検証、CSP、権限を制限したランタイムファイルを使用します。

## Development

テスト:

```bash
PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -v
node --check codex_rest/web/app.js
```

macOSアプリのビルドと署名確認:

```bash
/usr/bin/python3 build_macos_app.py
codesign --verify --deep --strict "build/Codex Rest.app"
```

プロジェクト構成:

```text
codex_rest/        Pythonデーモン、CLI、Web UI
macos_app/         ネイティブAppKitアプリ
tests/             状態管理、設定、HTTP、インストーラーのテスト
install.py         ユーザー領域へのインストーラー
build_macos_app.py .appバンドル生成スクリプト
```

## Privacy

- 外部サービスへ音源・プロンプト・Codex状態を送信しません。
- フックから取得するのはイベント名、`session_id`、`turn_id`だけです。
- ユーザー音源は `~/Library/Application Support/Codex Rest/media/` にコピーされます。
- 専用Chromeプロファイルを使用し、普段のChromeセッションへ干渉しません。

## Notes

- 初版はmacOSとGoogle Chromeを対象としています。
- 非管理フックはCodexの安全機構により、初回に利用者の信頼操作が必要です。
- PATH上の `codex` が利用できない場合でも、Codex App同梱CLIから `/hooks` を操作できます。

詳細な開発参加手順は [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。
