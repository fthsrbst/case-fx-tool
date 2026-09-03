#!/usr/bin/env bash
# Starts the service on $PORT (default 8080). The upstream base URL comes from
# $FX_UPSTREAM_BASE (default https://api.frankfurter.dev); nothing is hardcoded.
set -euo pipefail
cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  exec uv run --frozen uvicorn fx_tool.app:app --host 0.0.0.0 --port "${PORT:-8080}"
fi

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -e .
exec .venv/bin/uvicorn fx_tool.app:app --host 0.0.0.0 --port "${PORT:-8080}"
