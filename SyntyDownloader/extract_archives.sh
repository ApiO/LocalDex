#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

if [[ -x "$VENV_PYTHON" ]]; then
    exec "$VENV_PYTHON" "$SCRIPT_DIR/extract_archives.py" "$@"
fi

exec python3 "$SCRIPT_DIR/extract_archives.py" "$@"
