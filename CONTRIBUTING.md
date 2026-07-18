# Contributing

CodexWork HumanBreakへの改善提案を歓迎します。

## Setup

```bash
git clone https://github.com/senbaph08/CodexWork-HumanBreak.git
cd CodexWork-HumanBreak
```

Python側は標準ライブラリだけで動作します。macOSアプリをビルドする場合はXcode Command Line ToolsとGoogle Chromeが必要です。

## Checks

変更を送る前に次を実行してください。

```bash
PYTHONPATH=. /usr/bin/python3 -m unittest discover -s tests -v
node --check codex_rest/web/app.js
/usr/bin/python3 build_macos_app.py
codesign --verify --deep --strict "build/Codex Rest.app"
```

## Design guidelines

- Python 3.9で動作する構文を維持してください。
- 新しいPython依存関係は、標準ライブラリで解決できない場合だけ追加してください。
- プロンプト本文やトランスクリプトを保存・送信しないでください。
- 既存のCodex設定やフックを上書きせず、Codex Restの項目だけを変更してください。
- 音やアニメーションには、休憩を妨げる急激な音量変化や点滅を加えないでください。

## Pull requests

PRには変更理由、利用者への影響、実行したテストを記載してください。UI変更には可能であればスクリーンショットを添付してください。
