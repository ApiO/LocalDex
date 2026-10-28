#!/usr/bin/env bash
# Install the standalone Synty Store downloader on Linux.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
REQUIREMENTS="$SCRIPT_DIR/synty_requirements.txt"
WITH_SYSTEM_DEPS=0

usage() {
    cat <<'USAGE'
Usage: ./install_synty_sync.sh [--with-system-deps]

Creates SyntyDownloader/.venv, installs Python dependencies, and installs
Playwright Chromium. Use --with-system-deps if Chromium's Linux libraries are
missing; Playwright may request sudo to install OS packages.
USAGE
}

for arg in "$@"; do
    case "$arg" in
        --with-system-deps) WITH_SYSTEM_DEPS=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

find_python() {
    local candidate
    for candidate in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3; do
        [[ -n "$candidate" ]] || continue
        if ! command -v "$candidate" >/dev/null 2>&1; then
            continue
        fi
        if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

echo '=== SyntyDownloader — Linux setup ==='
if ! PYTHON_BIN="$(find_python)"; then
    cat >&2 <<'ERROR'
[ERROR] Python 3.10+ was not found.
Install Python 3.10 or newer and its venv support. On Debian/Ubuntu, for example:
  sudo apt update
  sudo apt install python3 python3-venv python3-pip
Then rerun this installer.
ERROR
    exit 1
fi
printf 'Python: %s\n' "$PYTHON_BIN"

if ! "$PYTHON_BIN" -c 'import venv' >/dev/null 2>&1; then
    cat >&2 <<'ERROR'
[ERROR] Python's venv module is unavailable.
On Debian/Ubuntu, install the matching python3-venv package, then rerun this installer.
ERROR
    exit 1
fi

if [[ -e "$VENV_DIR" && ! -x "$VENV_PYTHON" ]]; then
    echo "[ERROR] $VENV_DIR exists but has no usable Python interpreter." >&2
    echo 'Move or remove this incomplete virtual environment manually, then rerun.' >&2
    exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo 'Creating local Python virtual environment...'
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
if ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "[ERROR] $VENV_PYTHON is not a usable Python 3.10+ interpreter." >&2
    echo 'Move or remove SyntyDownloader/.venv manually, then rerun this installer.' >&2
    exit 1
fi

if [[ ! -f "$REQUIREMENTS" ]]; then
    echo "[ERROR] Requirements file not found: $REQUIREMENTS" >&2
    exit 1
fi

# A previous interrupted setup can leave a valid venv interpreter without pip.
# Try the interpreter's bundled ensurepip first, before running pip commands.
ensure_pip() {
    if "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
        return 0
    fi

    echo '[WARN] pip is missing from the downloader virtual environment.' >&2
    echo 'Attempting to bootstrap pip with Python ensurepip...' >&2
    if "$VENV_PYTHON" -m ensurepip --upgrade; then
        if "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
            echo '[OK] pip is available.'
            return 0
        fi
    fi

    local python_version
    python_version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    cat >&2 <<ERROR
[ERROR] Could not install pip into: $VENV_DIR

This usually means the OS package providing venv/ensurepip for Python $python_version
is missing. On Debian/Ubuntu, install the matching package(s):
  sudo apt update
  sudo apt install python3-venv python${python_version}-venv

Then rerun this installer. If the same incomplete environment is still detected,
move it aside first (it will be kept as a backup):
  mv "$VENV_DIR" "${VENV_DIR}.incomplete-$(date +%Y%m%d_%H%M%S)"
  "$SCRIPT_DIR/install_synty_sync.sh"
ERROR
    return 1
}

echo 'Checking pip in the virtual environment...'
ensure_pip || exit 1

echo 'Installing/updating Python dependencies...'
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$REQUIREMENTS"

echo 'Installing Playwright Chromium...'
if [[ "$WITH_SYSTEM_DEPS" -eq 1 ]]; then
    "$VENV_PYTHON" -m playwright install --with-deps chromium
else
    "$VENV_PYTHON" -m playwright install chromium
fi

echo 'Verifying dependencies and downloader syntax...'
"$VENV_PYTHON" -c 'import bs4, playwright, yaml'
"$VENV_PYTHON" -m py_compile "$SCRIPT_DIR/synty_sync.py"

if [[ -f "$PROJECT_ROOT/config.yaml" ]]; then
    "$VENV_PYTHON" "$SCRIPT_DIR/synty_sync.py" --check-config
else
    echo '[WARN] Root config.yaml not found.'
    echo "       Copy '$PROJECT_ROOT/config.example.yaml' to '$PROJECT_ROOT/config.yaml' and fill in login details."
fi

echo
echo 'SyntyDownloader Linux setup completed.'
echo 'Run a one-package interactive sign-in/test with:'
echo "  '$SCRIPT_DIR/run_synty_sync.sh'"
echo 'Or run the CLI directly with:'
echo "  '$VENV_PYTHON' '$SCRIPT_DIR/synty_sync.py' --check-config"
