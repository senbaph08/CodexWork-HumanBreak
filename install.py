#!/usr/bin/env python3
from pathlib import Path

from codex_rest.install import install


if __name__ == "__main__":
    wrapper = install(Path(__file__).resolve().parent)
    print("Codex Rest Window をインストールしました: {}".format(wrapper))
    print("Codexを再起動し、/hooks で4件のフックを確認・信頼してください。")
    print("設定画面: {} settings".format(wrapper))
