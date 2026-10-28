# SyntyDownloader — Windows and Linux

`synty_sync.py` is the shared Python command-line downloader for synchronizing
the Synty Store files available to your account. Windows and Linux have separate
install/run scripts; the download logic and configuration format are shared.

**Platform support:** SyntyDownloader CLI supports Windows and Linux. The
LocalDex web UI, indexer, and archive tools are **Windows-only**.

## What the downloader does

- Uses Chromium controlled by Playwright to access your Synty Store downloads.
- Supports interactive sign-in and email-delivered verification codes when the
  store requests them; it does not bypass CAPTCHA, MFA, or access controls.
- Follows the paginated library and visits the package download pages.
- Saves original files under `<output_dir>/<package name>/<filename>` without
  extracting, deleting, or silently overwriting downloaded archives.
- Stores a durable `.synty_history.json` so already downloaded files can be
  skipped on subsequent runs.
- Logs progress and failures in `.synty_sync.log`; failed transfers are not
  marked as successful.

## Shared configuration

The configuration is stored at the **repository root**, above `SyntyDownloader`:

```yaml
# config.yaml — private, Git-ignored
output_dir: SyntyLibrary
login:
  email: "your-email@example.com"
  password: ""                  # Optional; used only if the form asks for it
  customer_id: "1234567890123" # Numeric ID from the Synty Store downloads URL
```

If needed, copy the root `config.example.yaml` to root `config.yaml`, then fill
in the fields. Never commit or share `config.yaml`.

- A relative `output_dir` is resolved from the **configuration file's directory**,
  not from the current working directory. `SyntyLibrary` therefore points to the
  library folder beside `SyntyDownloader` and `SyntyLocalDex`.
- `--config PATH` can select a different YAML file. `--output PATH` is available
  as a manual override for the destination.
- The downloader stores its history and log in the destination library. Windows
  keeps using `.synty_browser_profile`; Linux uses `.synty_browser_profile_linux`
  so the two operating systems do not try to open the same Chromium profile.
- Do **not** run Windows and Linux syncs concurrently against the same library:
  the history and log files are shared. Close the first sync before starting the
  other one.

## Windows installation and use

Requirements: Windows 10/11 and Python 3.10+. At the repository root, run
`install.cmd` to install/repair the local virtual environment and Playwright
Chromium. For the downloader alone, `SyntyDownloader/install_synty_sync.ps1` is
the Windows installer called by `install.cmd`.

From the repository root, validate the configuration and test a single package:

```powershell
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --check-config
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --limit-packages 1
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --headless
```

`SyntyDownloader/run_synty_sync.cmd` runs the default two-stage workflow:
interactive sign-in and a one-package test, followed by a full headless sync.

## Linux installation and use

Requirements: Linux, Python 3.10+ with `venv` support, and internet access.
On Debian/Ubuntu, if Python or virtual-environment support is missing, install
it with:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

From the repository root, make the scripts executable and install the downloader:

```bash
chmod +x SyntyDownloader/install_synty_sync.sh SyntyDownloader/run_synty_sync.sh
./SyntyDownloader/install_synty_sync.sh
```

This creates `SyntyDownloader/.venv`, installs the Python dependencies, and
installs Playwright Chromium. If Chromium reports missing system libraries,
rerun the installer with `--with-system-deps`; Playwright may use `sudo` to
install OS packages:

```bash
./SyntyDownloader/install_synty_sync.sh --with-system-deps
```

Run the default interactive one-package test followed by a full headless sync:

```bash
./SyntyDownloader/run_synty_sync.sh
```

When arguments are provided, the shell launcher passes them directly to the
Python CLI, so individual operations can be run without the two-stage workflow:

```bash
./SyntyDownloader/run_synty_sync.sh --check-config
./SyntyDownloader/run_synty_sync.sh --limit-packages 1
./SyntyDownloader/run_synty_sync.sh --headless
./SyntyDownloader/run_synty_sync.sh --dry-run
```

Equivalent direct invocation from the repository root:

```bash
./SyntyDownloader/.venv/bin/python ./SyntyDownloader/synty_sync.py --check-config
```

**LocalDex is not available on Linux.** Use the downloader scripts to create or
update `SyntyLibrary`; open that library with LocalDex on a Windows machine.

## Useful CLI options

- `--check-config`: validate configuration without opening Chromium.
- `--limit-packages N`: test only the first `N` packages (`1` is recommended
  for the first run).
- `--headless`: run without a visible browser; requires a valid saved session.
- `--dry-run`: inspect the package list without downloading files or updating
  download history.
- `--delay SECONDS`: set the pause between downloads (default: `1`).
- `--max-pages N`: pagination safety limit (default: `500`).
- `--config PATH`: use an alternate configuration file.
- `--output PATH`: manually override `output_dir`.

If the session expires, run without `--headless` and complete the sign-in or
email-code step in Chromium. The profile is kept under the configured output
folder. Synty can change its page structure or authentication flow, so a future
site update may require selector changes.

## Destination layout

```text
SyntyLibrary/
  POLYGON - Adventure Pack/
    source_files.zip
  .synty_history.json
  .synty_sync.log
  .synty_browser_profile/         # Windows Chromium session
  .synty_browser_profile_linux/   # Linux Chromium session
  .synty-partials/                # Temporary transfer fragments, if any
```

Downloaded assets retain their own licenses. This tool does not alter the
account's purchases or attempt to bypass the store's access controls.
