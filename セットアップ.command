#!/bin/bash
# ダブルクリックでセットアップ画面を開く（macOS 用）。
# 初回は仮想環境の作成とライブラリのインストールを自動で行う。
cd "$(dirname "$0")" || exit 1

echo "Moodle アシスタントのセットアップを準備しています..."

if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "Python3 が見つかりません。"
    echo "https://www.python.org/downloads/ から Python をインストールしてください。"
    echo ""
    read -r -p "Enter キーで閉じます..."
    exit 1
fi

if [ ! -d venv ]; then
    echo "初回準備中です。数分かかることがあります..."
    python3 -m venv venv || { read -r -p "仮想環境の作成に失敗しました。Enter キーで閉じます..."; exit 1; }
fi

# shellcheck disable=SC1091
source venv/bin/activate

# requirements.txt が更新されたときだけ入れ直す
STAMP="venv/.requirements-stamp"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
    echo "必要なライブラリをインストールしています..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt || { read -r -p "インストールに失敗しました。Enter キーで閉じます..."; exit 1; }
    touch "$STAMP"
fi

# Gemini CLI（無ければ入れる。失敗してもセットアップは続行する）
if ! command -v gemini >/dev/null 2>&1; then
    if command -v npm >/dev/null 2>&1; then
        echo "Gemini CLI をインストールしています..."
        npm install -g @google/gemini-cli >/dev/null 2>&1 \
            || echo "  -> 失敗しました。あとで手動で: npm install -g @google/gemini-cli"
    else
        echo "Node.js が見つからないため Gemini CLI は入れられません。"
        echo "  Gemini から使う場合は https://nodejs.org/ から Node.js を入れてください。"
    fi
fi

echo "セットアップ画面を開きます。"
python setup_gui.py

echo ""
read -r -p "終了しました。Enter キーで閉じます..."
