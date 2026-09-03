#!/usr/bin/env bash
# Runs the tests. They need no network: the upstream is faked in-process, and
# $FX_UPSTREAM_BASE may point anywhere (we run it against a closed port).
set -euo pipefail
cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
  exec uv run --frozen --group dev pytest -q "$@"
fi

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -e . pytest
exec .venv/bin/pytest -q "$@"
