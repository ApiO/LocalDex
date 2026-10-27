# LocalDex — Synty Downloader & Local Asset Browser

Local, private tools to download, organize, index, explore, and safely extract the Synty Store assets available to your account.
Local Dex provides a Web UI for setup, catalog browsing, extraction, and statistics; the downloader is also available as a standalone command-line tool.

![LocalDex Web UI — Overview](docs/overview.jpg)
**Important:**
- This project is not affiliated with Synty Studios or OpenA.
- You must own the assets you download.
- Downloaded asset packs retain their own respective licenses
- The configuration file **`config.yaml`**, which contains your credentials, is **Git-ignored**.
## Quick start (Windows)
1. Clone/download the repository and keep the project folders together. The repository can be placed on any drive.
2. Copy **`config.example.yaml`** to **`config.yaml`** in the repository root. Do not share your information.
3. Run **`install.cmd`** in the repository root. It installs or reuses Python, creates the downloader virtual environment and installs Playwright/Chromium. Complete any email verification code (2FA) in the UI/browser.
4. Run **`launch_localdex.cmd`**, then open **http://127.0.0.1:8765**. On the **Configuration** page, use **Check again → Sync downloads → Sync assets / Rebuild index**.
### Finding `customer_id`

Sign in to [syntystore.com](https://syntystore.com/), open **My downloads**, and inspect the URL. Use the numeric value following `/apps/downloads/orders/`, which may also appear as the logged_in_customer_id` query parameter:

```text
https://syntystore.com/apps/downloads/orders/1234567890123?line_items_page=1
                                               └─ customer_id: 1234567890123
```

Configure **only the numeric ID**, not the full private URL or email OTP:
```yaml
# config.yaml — kept locally and ignored by Git
output_dir: SyntyLibrary
login:
  email: "your-email@example.com"
  password: ""
  customer_id: "1234567890123"
```
## Project layout
```text
LocalDex/
├── install.cmd                  # Windows setup / repair
├── launch_localdex.cmd          # Start local Web UI
├── config.example.yaml          # Safe, tracked template
├── config.yaml                  # Private, Git-ignored settings (local only)
├── README.md
├── logo.png                     # LocalDex book/search app icon (served by the local UI)
├── LICENSE                      # GNU GPL-3.0-only
├── NOTICE
├── docs/
│   ├── overview.jpg             # Web UI screenshot
│   ├── AI_ASSISTED_DEVELOPMENT.md
│   └── THIRD_PARTY_LICENSES.md
├── SyntyDownloader/             # Login + download synchronization
│   ├── synty_sync.py
│   ├── install_synty_sync.ps1
│   ├── run_synty_sync.cmd
│   └── README_synty_sync.md
├── SyntyLibrary/                # Downloaded assets, excluded from Git
│   └── <pack name>/
│       └── <downloaded files>
└── SyntyLocalDex/               # Local browser, indexer and APIs
    ├── local_dex_server.py
    ├── build_local_dex.py
    ├── local_dex_web/
    ├── README_LOCAL_DEX.md
    └── .localdex/               # Generated index/cache, ignored by Git
```
## Web UI
| Page | What it does |
| --- | --- |
| **Overview** | Browse entry point, packs and collections. |
| **Asset packs** | Browse pack covers, search/filter collections; a selected collection changes the heading. |
| **Pack Explorer** | Inspect a pack's discoverable assets and original downloaded files in **Grid/List** mode. Select an asset to view details without leaving the pack. |
| **Assets** | Search and filter all indexed assets, using **Grid/List** mode and the **Asset Details** inspector. |
| **Statistics** | Counts, storage, collections, categories, types, largest packages, and extraction metrics for supported archives, existing extraction folders, archives not yet extracted, recorded successful extractions, and the latest successful extraction. |
| **Extra tools → Extract archives** | Search by archive name, filter by available formats, show unextracted archives only, and browse collapsible package groups. Select archives and track completion with a percentage progress bar and timestamped log, with a failures-only view. Archive references open their containing folder. Successful extraction dates are saved per archive. Supported ZIP, TAR, TGZ, GZ and Unity package archives extract into sibling folders; originals are preserved. Re-extraction asks for confirmation, keeps identical files unchanged, renames changed old versions with a timestamp before the extension, and retains files absent from the new archive. RAR and 7z are listed but unsupported. |
| **Configuration** | Inspect setup readiness, install/repair components, edit configuration, sync downloads, rebuild the asset index, and read job status/logs. |

The left navigation sidebar can be collapsed to an icon rail on desktop; its state is saved in the browser. The **Asset Details** side panel can be resized horizontally by dragging its
left edge (from its default width up to twice that width). Asset lists load
more results automatically near the bottom; the manual **Load more** option
remains. View-mode and Light/Dark theme preferences are saved in the browser.
Previews include images, animated images, audio/video, OBJ and supported FBX
static meshes, including entries in ZIP and Unity packages. Some FBX materials,
textures, skeletons and animations are not rendered. A supported image in the
root of a pack folder is preferred for its cover (alphabetical selection).
The indexer reads archive contents without modifying the original downloads.
## Optional: Run SyntyDownloader directly

Use these commands **from the repository root**, after running `install.cmd`:

```powershell
# Validate configuration without logging in
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --check-config

# Interactive sign-in / first-pack smoke test
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --limit-packages 1
# Full sync using a valid saved browser session
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --headless
```

Alternatively, run `SyntyDownloader/run_synty_sync.cmd` for an interactive
one-pack sync followed by a full headless sync. For index-only updates, use
`SyntyLocalDex/rebuild_local_dex.cmd` or **Configuration → Sync assets**.
See the [downloader guide](SyntyDownloader/README_synty_sync.md) and
[Local Dex guide](SyntyLocalDex/README_LOCAL_DEX.md) for technical details.
## Privacy, security and troubleshooting
- The server listens on **127.0.0.1:8765**; keep the server terminal open.
- **Never commit** root `config.yaml`, Chromium profiles, `.synty_history.json`,
  logs, indexes, or downloaded assets. See [`.gitignore`](.gitignore).
- If downloads require an email verification code, sync without `--headless`
  and complete the authentication in the UI or browser.
- If downloads aren't visible, use **Configuration → Sync assets / Rebuild
  index**.
- If Python or Chromium is missing, run **`install.cmd`**, or use the UI's
  **Install / Repair** action where available.
- If the local server cannot use port 8765, stop the previous instance or
  run `SyntyLocalDex/local_dex_server.py --port 8766`.
- For stale UI branding, use `Ctrl+F5` to refresh the browser cache.
- If secrets were **already committed**, `.gitignore` does not remove them
  from Git history. Remove tracked copies and rotate exposed credentials.
## License, attribution and third-party content

The project's **first-party software** is offered under the
[GNU General Public License version 3 only](LICENSE) (`GPL-3.0-only`), to the
extent that contributors have the rights required to grant the license.
Redistributed GPL-covered versions must comply with the GPL's applicable
notices and corresponding-source requirements. See [NOTICE](NOTICE) for
project attribution and the [original repository](https://github.com/ApiO/LocalDex).
**AI-assisted development:** ChatGPT has helped generate or refine parts of
the code, documentation and visual assets. The contributors direct and review
the development. This does not automatically confer copyright protection on
every generated output. See the
[AI-assisted development statement](docs/AI_ASSISTED_DEVELOPMENT.md).
Dependencies and downloaded content keep their own rights and conditions:
see [Third-party software and content](docs/THIRD_PARTY_LICENSES.md).
In particular, **Synty assets are not relicensed under GPL-3.0**.
