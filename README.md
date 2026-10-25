# Synty Local Dex & Downloader

Local, private tools to **download, organize, index and explore the Synty Store assets available to your account**.

Local Dex provides a Web UI for setup and daily use; the downloader is also available as a standalone command-line tool.

![Local Dex Web UI — Overview](docs/overview.jpg)

### Disclaimers:

- This project is not affiliated with Synty Studios.
- You must own the assets you download.
- Downloaded asset packs remain subject to their own respective licenses;
- The configuration file **`config.yaml`**, which contains your credentials, is **Git-ignored**. Do not share your information.

## Quick start (Windows)

1. Clone or extract the repository, keeping `SyntyDownloader`, `SyntyLibrary` and `SyntyLocalDex` as **sibling directories**. There is no fixed drive or install path.
2. Create a file **`config.yaml`** at project's root level with content:
```
output_dir: SyntyLibrary

login:
  email: "your-email@example.com" # your synty account email
  password: ""                    # your synty account password
  customer_id: "YOUR_CUSTOMER_ID" # your synty account Id
```
> Finding your Synty `customer_id`
> 
> 1. Sign in at [syntystore.com](https://syntystore.com/).
> 2. Open **My downloads** in your account.
> 3. Look at the page URL. Your `customer_id` is the numeric ID after `/apps/downloads/orders/` (and may also appear as `logged_in_customer_id`).
> For example:
> 
> ```text
> https://syntystore.com/apps/downloads/orders/1234567890123?logged_in_customer_id=1234567890123&line_items_page=1
> ==> customer_id=1234567890123
> ```
> Enter **only the digits**, not the whole URL. This is a customer identifier, not your email verification code. Do not share private download links or session cookies.
3. Double-click **`install.cmd`** at the repository root. It installs or reuses Python (3.10+), creates the downloader virtual environment and installs Playwright/Chromium. Complete any email verification code (2FA) in the UI/browser.
4. Double-click **`launch_localdex.cmd`**. The Web UI opens at **http://127.0.0.1:8765**; leave the console running.
5. In **Configuration**, click **Check again (optional) → Sync downloads → Sync assets / Rebuild index**.

**That's it.** Use the **Assets**, **Asset packs**, **Statistics**, and **Configuration** pages to manage your local collection. Existing downloads are never deleted or overwritten by the downloader. To skip downloading, use **Sync assets / Rebuild index** to index an existing library.

### How it works for short

SyntyDownloader simulates browsing the syntystore.com website using your account and downloads your packages into the folder you have configured.
SyntyDownloader will only download files that are not already present and will never delete anything from your folders.

SyntyLocalDex will then access the download folder to use it as a data source.

## Repository structure

```text
Synty/                          # Repository root; can be on any drive
├── install.cmd                 # First-time setup / repair
├── launch_localdex.cmd         # Start the Web UI
├── config.example.yaml         # Safe template (tracked)
├── config.yaml                 # Private credentials (ignored)
├── README.md
├── LICENSE                     # GPL-3.0-only
├── NOTICE
├── docs/
│   └── overview.jpg
├── SyntyDownloader/
│   ├── synty_sync.py           # Downloader and email-code authentication
│   ├── install_synty_sync.ps1  # Installer engine called by install.cmd
│   ├── run_synty_sync.cmd      # Optional standalone downloader
│   ├── run_synty_sync.ps1
│   ├── synty_requirements.txt
│   └── .venv/                  # Installed locally (ignored)
├── SyntyLibrary/
│   └── <package name>/         # Downloaded packages (ignored)
│       ├── Pack_Preview.jpg
│       ├── Asset.zip
│       └── ...
└── SyntyLocalDex/
    ├── local_dex_server.py
    ├── build_local_dex.py
    ├── local_dex_web/         # Web UI, styles, scripts, logos, favicon
    ├── rebuild_local_dex.cmd  # Optional direct indexing
    └── .localdex/             # Generated SQLite catalog and caches (ignored)
```

## Using the Web UI

| Page | Features |
| --- | --- |
| **Overview** | Entry point to browse local packages and collections. |
| **Asset packs** | Browse package covers and collections. Click a pack to open **Pack Explorer**. The title changes to `COLLECTION: <name>` when a collection is selected. |
| **Pack Explorer** | Browse discoverable assets and original downloaded files in **Grid or List** mode. Click an asset to inspect its details in the right panel **without leaving the pack**. |
| **Assets** | Search across all indexed assets. Filter by collection, category, type or engine; choose **Grid or List**. Click an item to open **Asset Details**. |
| **Statistics** | View pack and asset counts, storage, types, categories and largest packages. |
| **Configuration** | Check setup readiness, install/repair dependencies, edit root `config.yaml`, synchronize downloads, rebuild the index, view execution timestamps, status and logs. |

The **Asset Details** panel supports resizing by dragging its left edge (from the original width up to double). The pages automatically **Load more** on scroll; the manual button remains available. Toggle **Light / Dark** in the sidebar; both the theme and view preferences persist in browser storage.

**Previews** include images, animated GIFs, video, audio, OBJ, and supported **FBX static meshes** (including files inside ZIP or Unity packages). These previews are lightweight: FBX materials, textures, rigging and animations may not be reproduced. When a supported image is found directly at a package folder's root, the first image alphabetically is used as its cover. The indexer does not extract or delete original downloads.

## Optional: Use SyntyDownloader directly

Everything available on the **Configuration** page can also be run without the Web UI:

```powershell
# From the repository root, after install.cmd
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --check-config

# Interactive login / one-package smoke test
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --limit-packages 1

# Full sync using a saved login session
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --headless
```

Or run `SyntyDownloader/run_synty_sync.cmd` for interactive one-package sync followed by full headless synchronization. All commands load the **root** `config.yaml` automatically. If the session expires, rerun interactively to complete authentication. Successive runs skip downloaded files recorded in `SyntyLibrary/.synty_history.json` when the corresponding files still exist.

For an index-only run (no downloader required), use `SyntyLocalDex/rebuild_local_dex.cmd` or the Configuration page's **Sync assets / Rebuild index** action.

## Security, privacy & Git

- Local Dex listens on **127.0.0.1:8765**. Its catalog and previews are served locally; synchronization contacts Synty Store only when explicitly launched.
- Never commit `config.yaml`, `.synty_browser_profile`, `.synty_history.json`, `.venv`, `.localdex`, logs or downloads. See [`.gitignore`](.gitignore).
- The private SyntyLibrary files belong to their own asset-license terms, not the project's GPL license.
- The `.cmd` entry points use a **process-only** PowerShell execution-policy override. Organization-wide policies can still restrict scripts.
- If an existing Git repository previously tracked a configuration file, `.gitignore` will not remove it from Git history: use `git rm --cached config.yaml` (or `git rm --cached SyntyDownloader/config.yaml`) and rotate any exposed credentials.

## Troubleshooting

| Symptom | Suggested fix |
| --- | --- |
| Python missing or downloader unavailable | Run **`install.cmd`**. The UI can also use **Install / Repair**. |
| Download sync reports missing/invalid configuration | Open **Configuration → Open config.yaml**, fill email and `customer_id`, save, and click **Check again**. |
| An existing install lost its library path | In root `config.yaml`, set `output_dir: SyntyLibrary` for the default sibling layout. If you used a custom location before migration, the migration script preserves its target. |
| Authentication requires an email code | Launch **Sync downloads** without Headless mode and finish sign-in. |
| New downloaded files are not visible | Run **Configuration → Sync assets / Rebuild index**. |
| Local Dex server cannot bind port 8765 | Close the previous instance, or run `SyntyLocalDex/local_dex_server.py --port 8766`. |
| Favicon/logo appears stale | Hard refresh your browser using `Ctrl+F5`. |

See [Downloader guide](SyntyDownloader/README_synty_sync.md) and [Local Dex guide](SyntyLocalDex/README_LOCAL_DEX.md) for technical details.
