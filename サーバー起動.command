#!/bin/bash
# 学生の Claude から使えるように、MCP サーバを公開する（macOS 用）。
# ダブルクリックで起動し、公開アドレスを表示する。
# 閉じるとサーバも止まるので、デモ中は開いたままにすること。
cd "$(dirname "$0")" || exit 1

PORT="${PORT:-8000}"

if [ ! -x venv/bin/python ]; then
    echo "先に「セットアップ.command」を実行してください。"
    read -r -p "Enter キーで閉じます..."
    exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
    echo "cloudflared が見つかりません。次のコマンドで入れてください:"
    echo "    brew install cloudflared"
    read -r -p "Enter キーで閉じます..."
    exit 1
fi

LOG="$(mktemp -t moodle-tunnel)"
cleanup() {
    echo ""
    echo "停止しています..."
    [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    rm -f "$LOG"
}
trap cleanup EXIT INT TERM

echo "MCP サーバを起動しています..."
venv/bin/python remote_server.py --port "$PORT" &
SERVER_PID=$!

sleep 2
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "サーバの起動に失敗しました。"
    read -r -p "Enter キーで閉じます..."
    exit 1
fi

echo "公開アドレスを取得しています..."
cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate > "$LOG" 2>&1 &
TUNNEL_PID=$!

PUBLIC=""
for _ in $(seq 1 30); do
    PUBLIC=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1)
    [ -n "$PUBLIC" ] && break
    sleep 2
done

if [ -z "$PUBLIC" ]; then
    echo "公開アドレスを取得できませんでした。ネットワークを確認してください。"
    read -r -p "Enter キーで閉じます..."
    exit 1
fi

echo ""
echo "============================================================"
echo " 学生に伝えるサーバーのアドレス"
echo ""
echo "   $PUBLIC"
echo ""
echo " 学生はセットアップ画面でこのアドレスを入れると、"
echo " 自分専用の URL が表示されます。"
echo "============================================================"
echo ""
echo "この画面を閉じるとサーバも止まります。Ctrl+C で終了。"

wait "$SERVER_PID"
