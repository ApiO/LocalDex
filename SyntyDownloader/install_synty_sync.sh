#!/usr/bin/env bash
# Install the standalone Synty Store downloader on Linux (including WSL2).
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

Run this installer as your normal Linux user, not with sudo. WSL2 is supported.
USAGE
}

for arg in "$@"; do
    case "$arg" in
        --with-system-deps) WITH_SYSTEM_DEPS=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

# Keep the virtual environment and Playwright cache owned by the user who runs
# the downloader. A root-owned venv can break later launches from a normal shell.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    cat >&2 <<'ERROR'
[ERROR] Do not run this installer as root or with sudo.
It installs a user-owned Python environment and Playwright browser cache.
Run it from your normal WSL/Linux user shell instead:
  ./SyntyDownloader/install_synty_sync.sh
ERROR
    exit 1
fi

find_python() {
    local candidate
    local -a candidates=()

    if [[ -n "${PYTHON:-}" ]]; then
        candidates+=("$PYTHON")
    fi

    # Discover installed versioned interpreters (including newer versions such
    # as python3.14) instead of maintaining a fixed list in the installer.
    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] || continue
        [[ "$candidate" == "${PYTHON:-}" ]] || candidates+=("$candidate")
    done < <(compgen -c | grep -E '^python3\.[0-9]+$' | sort -Vr | uniq || true)
    candidates+=(python3)

    for candidate in "${candidates[@]}"; do
        [[ -n "$candidate" ]] || continue
        if ! command -v "$candidate" >/dev/null 2>&1; then
            continue
        fi
        if "$candidate" -c 'import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

echo '=== SyntyDownloader — Linux / WSL2 setup ==='
if ! PYTHON_BIN="$(find_python)"; then
    cat >&2 <<'ERROR'
[ERROR] Python 3.10+ with the standard-library venv module was not found.
Install Python 3.10 or newer and your distribution's venv support, then rerun.
On Debian/Ubuntu (including Ubuntu on WSL2), this is commonly provided by
python3-venv or a version-specific package such as python3.14-venv.
For other distributions, install the equivalent package using its package manager.
ERROR
    exit 1
fi
printf 'Python: %s\n' "$PYTHON_BIN"

if [[ ! -f "$REQUIREMENTS" ]]; then
    echo "[ERROR] Requirements file not found: $REQUIREMENTS" >&2
    exit 1
fi

if [[ ! -w "$SCRIPT_DIR" ]]; then
    echo "[ERROR] The project directory is not writable by user $(id -un): $SCRIPT_DIR" >&2
    echo 'Ensure the project files are owned by your normal user, then rerun without sudo.' >&2
    exit 1
fi
if [[ -e "$VENV_DIR" && ! -w "$VENV_DIR" ]]; then
    echo "[ERROR] The virtual environment is not writable by user $(id -un): $VENV_DIR" >&2
    echo 'It may have been created by an earlier sudo run. Restore ownership, for example:' >&2
    printf '  sudo chown -R %q:%q %q\n' "$(id -un)" "$(id -gn)" "$VENV_DIR" >&2
    exit 1
fi

if [[ -e "$VENV_DIR" && ! -x "$VENV_PYTHON" ]]; then
    echo "[ERROR] $VENV_DIR exists but has no usable Python interpreter." >&2
    echo 'Move this incomplete virtual environment to a backup, then rerun.' >&2
    exit 1
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo 'Creating local Python virtual environment (pip bootstrap is handled separately)...'
    if ! "$PYTHON_BIN" -m venv --without-pip "$VENV_DIR"; then
        echo "[ERROR] Could not create the virtual environment at: $VENV_DIR" >&2
        echo 'Check that your Python installation includes the venv module and that the directory is writable.' >&2
        exit 1
    fi
fi

if ! "$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "[ERROR] $VENV_PYTHON is not a usable Python 3.10+ interpreter." >&2
    echo 'Move or rename SyntyDownloader/.venv, then rerun this installer.' >&2
    exit 1
fi

# Repair an incomplete venv without deleting it. Some distro Python builds omit
# ensurepip; in that case, bootstrap pip from the official PyPA HTTPS endpoint.
ensure_pip() {
    local bootstrap_script
    local python_version

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
    else
        echo '[INFO] ensurepip is unavailable in this Python build.' >&2
    fi

    echo 'Attempting the official PyPA get-pip.py bootstrap over HTTPS...' >&2
    if ! bootstrap_script="$(mktemp "${TMPDIR:-/tmp}/localdex-get-pip.XXXXXX.py")"; then
        echo '[ERROR] Could not create a temporary file for the pip bootstrap.' >&2
        return 1
    fi

    if command -v curl >/dev/null 2>&1; then
        if ! curl --fail --location --silent --show-error --retry 2 \
            --connect-timeout 15 'https://bootstrap.pypa.io/get-pip.py' \
            --output "$bootstrap_script"; then
            rm -f -- "$bootstrap_script"
            echo '[ERROR] Could not download the official pip bootstrap script with curl.' >&2
            print_pip_recovery
            return 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -q 'https://bootstrap.pypa.io/get-pip.py' -O "$bootstrap_script"; then
            rm -f -- "$bootstrap_script"
            echo '[ERROR] Could not download the official pip bootstrap script with wget.' >&2
            print_pip_recovery
            return 1
        fi
    else
        if ! "$PYTHON_BIN" - "$bootstrap_script" <<'PYBOOTSTRAP'
import sys
import urllib.request
urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", sys.argv[1])
PYBOOTSTRAP
        then
            rm -f -- "$bootstrap_script"
            echo '[ERROR] Could not download the official pip bootstrap script with Python.' >&2
            print_pip_recovery
            return 1
        fi
    fi

    if ! "$VENV_PYTHON" "$bootstrap_script" --disable-pip-version-check; then
        rm -f -- "$bootstrap_script"
        echo '[ERROR] The pip bootstrap script failed.' >&2
        print_pip_recovery
        return 1
    fi
    rm -f -- "$bootstrap_script"

    if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
        echo '[ERROR] pip is still unavailable after bootstrapping.' >&2
        print_pip_recovery
        return 1
    fi
    echo '[OK] pip is available.'
}

print_pip_recovery() {
    local distro_id=''
    local distro_like=''
    local python_version='unknown'
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        distro_id="${ID:-}"
        distro_like="${ID_LIKE:-}"
    fi
    python_version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || printf unknown)"
    cat >&2 <<ERROR

[RECOVERY] pip could not be bootstrapped for Python $python_version.
Distribution: ${distro_id:-unknown}${distro_like:+ (based on $distro_like)}
Install the venv/ensurepip support package matching this Python version using
your distribution's package manager, then move the incomplete environment aside
and rerun the installer. On Debian/Ubuntu, for example, try:
  sudo apt update
  sudo apt install python${python_version}-venv
If that versioned package is unavailable, check whether python3-venv is provided.
ERROR
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
echo 'SyntyDownloader Linux / WSL2 setup completed.'
echo 'Run a one-package interactive sign-in/test with:'
echo "  '$SCRIPT_DIR/run_synty_sync.sh'"
echo 'Or run the CLI directly with:'
echo "  '$VENV_PYTHON' '$SCRIPT_DIR/synty_sync.py' --check-config"
