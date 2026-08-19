#!/usr/bin/env bash
# Protocol-level verification of the hosted MCP server using the real
# Anthropic @modelcontextprotocol/inspector tool in its --cli mode.
#
# This proves the OAuth-gated protocol surface is wired correctly WITHOUT a
# live Yahoo account: dummy Yahoo credentials are enough to prove the server
# advertises OAuth metadata correctly and refuses unauthenticated tool calls.
# It does NOT prove tool results are correct against live Yahoo data — that
# requires gates G1-G3 in specs/002-hosted-multitenant-mcp/quickstart.md and
# a real interactive OAuth login (see the bottom of this script).
#
# Usage: scripts/verify-mcp-protocol.sh
set -euo pipefail

cd "$(dirname "$0")/.."

DB_PATH="$(mktemp -u /tmp/verify-mcp-protocol.XXXXXX.db)"
PORT="${PORT:-8000}"
BASE_URL="http://localhost:${PORT}"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$DB_PATH"
}
trap cleanup EXIT

echo "Starting server with dummy Yahoo credentials on ${BASE_URL} ..."
YAHOO_CLIENT_ID=dummy YAHOO_CLIENT_SECRET=dummy \
  PUBLIC_BASE_URL="$BASE_URL" DB_PATH="$DB_PATH" PORT="$PORT" \
  .venv/bin/python -m yahoo_fantasy_mcp > /tmp/verify-mcp-protocol.server.log 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 20); do
  if curl -sS -o /dev/null "$BASE_URL/.well-known/oauth-authorization-server"; then
    break
  fi
  sleep 0.5
done

echo
echo "== OAuth authorization server metadata =="
curl -sS "$BASE_URL/.well-known/oauth-authorization-server" | python3 -m json.tool

echo
echo "== OAuth protected resource metadata (scoped to /mcp) =="
curl -sS "$BASE_URL/.well-known/oauth-protected-resource/mcp" | python3 -m json.tool

echo
echo "== Unauthenticated POST /mcp (expect 401 + WWW-Authenticate) =="
curl -sS -i -X POST "$BASE_URL/mcp" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | head -20

echo
echo "== Real @modelcontextprotocol/inspector --cli tools/list (expect auth_required) =="
set +e
npx -y @modelcontextprotocol/inspector --cli \
  --server-url "$BASE_URL/mcp" --transport http \
  --method tools/list --stored-auth-only --format json
INSPECTOR_EXIT=$?
set -e
echo "inspector-cli exit code: $INSPECTOR_EXIT (3 = auth_required, expected without a real Yahoo login)"

echo
echo "Done. To go further once gate G1 clears (approved Yahoo API access):"
echo "  npx -y @modelcontextprotocol/inspector --cli --server-url $BASE_URL/mcp \\"
echo "    --transport http --method tools/list --format json"
echo "  (drop --stored-auth-only; this opens a real interactive Yahoo OAuth login)"
