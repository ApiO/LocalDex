# Installing SyntyDownloader on Windows

For the simplest workflow, follow the [root README](../README.md) and use the
LocalDex **Configuration** page for installation status and synchronization.

## Recommended setup

1. Clone or extract the repository into a folder of your choice. Keep
   `SyntyDownloader`, `SyntyLibrary`, and `SyntyLocalDex` as sibling directories.
2. Copy the root `config.example.yaml` to `config.yaml` and provide your
   Synty Store email and numeric `customer_id` (shown in your **My downloads**
   URL, after `/apps/downloads/orders/`). The password can usually be blank.
3. Double-click **`install.cmd`** at the repository root. It installs or
   reuses Python 3.10+, creates `SyntyDownloader/.venv`, installs packages,
   and downloads Playwright Chromium.
4. Double-click **`launch_localdex.cmd`**. Open
   `http://127.0.0.1:8765` and use **Configuration** to check readiness,
   synchronize downloads, and rebuild the asset index.

The root launchers can initialize root `config.yaml` from the example or
migrate the legacy `SyntyDownloader/config.yaml`. Check the resulting
`output_dir`: with a root YAML and sibling folders, use `SyntyLibrary`.

## Direct commands (optional)

Open PowerShell at the **repository root** after installation:

```powershell
# Inspect YAML configuration without starting a browser
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --check-config

# First login / download from one pack
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --limit-packages 1

# Synchronize all packs using an existing authenticated session
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --headless
```

You can also run `SyntyDownloader/run_synty_sync.cmd`, which performs an
interactive one-pack stage followed by a headless full sync. If authentication
expires, use the interactive mode and enter the email verification code.

## Troubleshooting and safety

- **Python not found:** if `winget` is unavailable or restricted, install
  Python 3.10+ manually and rerun `install.cmd`.
- **Missing packages/Chromium:** rerun `install.cmd` to repair installation.
- **PowerShell execution policy:** `install.cmd` uses a process-level policy
  override; it does not permanently relax Windows settings. Organization
  policies can still block scripts.
- **Browser download size:** Chromium and dependencies can occupy several
  hundred MB, depending on platform and version.
- **Protect secrets:** root `config.yaml`, browser profiles, history, and
  logs should never be committed or shared. See [`.gitignore`](../.gitignore).
- **Already installed?** Rerunning the installer does not delete downloaded
  asset files.

More advanced options: [downloader guide](README_synty_sync.md).
Licensing and attribution: [NOTICE](../NOTICE) and
[AI-assisted development](../docs/AI_ASSISTED_DEVELOPMENT.md).
