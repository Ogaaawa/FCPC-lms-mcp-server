#!/bin/bash
# Double-click to publish the MCP server so students can use it from Claude.
# It prints the URL your students need. Closing this window stops the server,
# so leave it open while the service is in use.
cd "$(dirname "$0")" || exit 1

PORT="${PORT:-8000}"

if [ ! -x venv/bin/python ]; then
    echo "Run setup.command first."
    read -r -p "Press Enter to close..."
    exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
    echo "cloudflared was not found. Install it with:"
    echo "    brew install cloudflared"
    read -r -p "Press Enter to close..."
    exit 1
fi

LOG="$(mktemp -t moodle-tunnel)"
cleanup() {
    echo ""
    echo "Shutting down..."
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
    rm -f "$LOG"
}
trap cleanup EXIT INT TERM

# The public address has to exist before the server starts, because it
# becomes the OAuth issuer.
echo "Requesting a public address..."
cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate > "$LOG" 2>&1 &
TUNNEL_PID=$!

PUBLIC=""
for _ in $(seq 1 30); do
    PUBLIC=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1)
    [ -n "$PUBLIC" ] && break
    sleep 2
done

if [ -z "$PUBLIC" ]; then
    echo "Could not get a public address. Check your network connection."
    read -r -p "Press Enter to close..."
    exit 1
fi

echo "Starting the MCP server..."
venv/bin/python remote_server.py --port "$PORT" --public-url "$PUBLIC" &
SERVER_PID=$!

sleep 3
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "The server failed to start."
    read -r -p "Press Enter to close..."
    exit 1
fi

echo ""
echo "============================================================"
echo " Give this URL to your students (the same one for everyone)"
echo ""
echo "   $PUBLIC/mcp"
echo ""
echo " They paste it into Claude under"
echo " Settings > Connectors > Add custom connector."
echo " Claude opens the Moodle sign-in page automatically."
echo "============================================================"
echo ""
echo "Closing this window stops the server. Press Ctrl+C to quit."

wait "$SERVER_PID"
