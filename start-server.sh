#!/bin/bash
# Publish the MCP server with a temporary Cloudflare quick tunnel.
# Linux and macOS. For a permanent install use a named tunnel and the systemd
# unit in deploy/ instead - see DEPLOYMENT.md.
#
#   ./start-server.sh
#   PORT=9000 ./start-server.sh
set -u
cd "$(dirname "$0")" || exit 1

PORT="${PORT:-8000}"
PYTHON="venv/bin/python"

die() {
    echo "$1" >&2
    [ -t 0 ] && read -r -p "Press Enter to close..."
    exit 1
}

[ -x "$PYTHON" ] || die "No virtual environment. Run: python -m venv venv && venv/bin/pip install -r requirements.txt"
command -v cloudflared >/dev/null 2>&1 || die "cloudflared was not found. Install it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"

LOG="$(mktemp -t moodle-tunnel.XXXXXX)"
SERVER_PID=""
TUNNEL_PID=""
cleanup() {
    echo ""
    echo "Shutting down..."
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
    [ -n "$TUNNEL_PID" ] && kill "$TUNNEL_PID" 2>/dev/null
    rm -f "$LOG"
}
trap cleanup EXIT INT TERM

# The public address has to exist before the server starts, because it becomes
# the OAuth issuer.
echo "Requesting a public address..."
cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate > "$LOG" 2>&1 &
TUNNEL_PID=$!

PUBLIC=""
for _ in $(seq 1 30); do
    PUBLIC=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1)
    [ -n "$PUBLIC" ] && break
    sleep 2
done
[ -n "$PUBLIC" ] || die "Could not get a public address. Check the network connection."

echo "Starting the MCP server..."
"$PYTHON" remote_server.py --port "$PORT" --public-url "$PUBLIC" &
SERVER_PID=$!

sleep 3
kill -0 "$SERVER_PID" 2>/dev/null || die "The server failed to start."

echo ""
echo "============================================================"
echo " Give this URL to your students (the same one for everyone)"
echo ""
echo "   $PUBLIC/mcp"
echo ""
echo " They paste it into Claude under"
echo " Settings > Connectors > Add custom connector."
echo "============================================================"
echo ""
echo "This address disappears when this process stops, and a new one is"
echo "issued next time. For a fixed address see DEPLOYMENT.md."
echo "Press Ctrl+C to quit."

wait "$SERVER_PID"
