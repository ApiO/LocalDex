# Synty Downloader — Windows installation

Prefer the [repository root README](../README.md) for the recommended **Web UI workflow**.

## Setup

1. Run **`../install.cmd`** from the repository root. It detects or installs Python 3.10+, creates `SyntyDownloader/.venv` and installs Python packages plus Playwright Chromium.
2. Run **`../launch_localdex.cmd`** to open the browser at `http://127.0.0.1:8765`.
3. On the **Configuration** page, select **Open config.yaml** and enter your Synty Store email and `customer_id`.
4. Run **Sync downloads** and **Sync assets / Rebuild index** from the same page.

On first launch, the root launchers create `../config.yaml` from `../config.example.yaml` if missing, or safely migrate a legacy `SyntyDownloader/config.yaml` to the root. For the standard sibling layout, configure:

```yaml
output_dir: SyntyLibrary
login:
  email: "your-email@example.com"
  password: ""
  customer_id: "1234567890123"
```

Find your numeric customer ID in the Synty Store **My downloads** URL: `.../apps/downloads/orders/<customer_id>`. Do not use the full URL.

## Standalone commands

From the repository root, after installation:

```powershell
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --check-config
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --limit-packages 1
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --headless
```

You can also run `SyntyDownloader/run_synty_sync.cmd` to perform the interactive stage, then a full headless sync. The root YAML is always the default configuration for these commands.

## Notes

- The root `install.cmd` uses `powershell.exe -ExecutionPolicy Bypass` **only for the launched process**; it does not change Windows policy permanently.
- Re-running the installer repairs packages without deleting downloaded assets.
- Python dependencies and browser binaries may use several hundred MB.
- If `winget` is unavailable, install Python 3.10+ manually and rerun `install.cmd`.
- Private `config.yaml`, Chromium profiles, and download history are excluded by the repository `.gitignore` and must not be committed.
