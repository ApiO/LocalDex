#!/usr/bin/env bash
# Run the standalone Synty Store downloader on Linux.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
SYNC_SCRIPT="$SCRIPT_DIR/synty_sync.py"

if [[ ! -x "$PYTHON" ]]; then
    echo '[ERROR] SyntyDownloader is not installed for Linux.' >&2
    echo "Run: '$SCRIPT_DIR/install_synty_sync.sh'" >&2
    exit 1
fi
if [[ ! -f "$SYNC_SCRIPT" ]]; then
    echo "[ERROR] Downloader script not found: $SYNC_SCRIPT" >&2
    exit 1
fi

# If arguments are supplied, expose the full Python CLI unchanged.
if [[ "$#" -gt 0 ]]; then
    exec "$PYTHON" "$SYNC_SCRIPT" "$@"
fi

# Default interactive workflow mirrors the Windows launcher: validate config,
# sign in visibly and test one package, then perform the complete headless sync.
"$PYTHON" "$SYNC_SCRIPT" --check-config

echo
echo 'Step 1/2: interactive sign-in and one-package test...'
"$PYTHON" "$SYNC_SCRIPT" --limit-packages 1

echo
echo 'Step 2/2: full headless synchronization...'
"$PYTHON" "$SYNC_SCRIPT" --headless

echo 'SyntyDownloader synchronization completed.'
