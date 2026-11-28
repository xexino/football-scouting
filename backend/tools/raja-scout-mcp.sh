#!/usr/bin/env bash
# Launch the Raja Scout MCP server over stdio for a local development agent (see .mcp.json).
# Needs the same DATABASE_URL and SECRET_KEY as the running backend, and RAJA_SCOUT_MCP_TOKEN
# (an access token from POST /api/auth/token). Nothing secret is stored in this repository.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m app.mcp "$@"
