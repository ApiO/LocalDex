# Synty Library — Downloader & LocalDex

A local workflow for **downloading, organizing, indexing, and browsing a personal [Synty Store](https://syntystore.com/) asset library** on Windows.

This repository contains three neighboring folders with separate responsibilities:

| Folder | Responsibility | Tracked in Git? |
| --- | --- | --- |
| [`SyntyDownloader/`](SyntyDownloader/) | Sign in to Synty Store, download entitled packages, and remember completed downloads. | **Yes**, except runtime files and secrets. |
| [`SyntyLibrary/`](SyntyLibrary/) | Store the original downloaded packages and related files, grouped by package name. | **No** downloaded assets; optionally track `.gitkeep`. |
| [`SyntyLocalDex/`](SyntyLocalDex/) | Build a searchable offline catalog and serve a local asset browser. | **Yes**, except generated indexes and caches. |

> **Disclaimers:**
- LocalDex is inspired by [Synty(r) Dex](https://dex.syntystore.com/) but is not an official product of Synty Studios.
- The download tool only accesses files available to the logged-in account. None of its components bypass the site's access controls.
- Should the structure of the official Synty website change, this solution will cease to function and an update will be required.
- If an official API becomes available in the future, this solution will utilize it.

## 1. Repository layout

```text
<root>/                             # Git repository root; any drive or parent folder
├── .gitignore
├── README.md                       # This file
├── SyntyDownloader/
│   ├── synty_sync.py               # Store sync and download logic
│   ├── synty_requirements.txt
│   ├── config.example.yaml         # Safe template; tracked
│   ├── config.yaml                 # Local credentials; Git-ignored
│   ├── install_synty_sync.cmd      # Windows installer entry point
│   ├── install_synty_sync.ps1
│   ├── run_synty_sync.cmd          # Downloader-only launcher
│   ├── run_synty_sync.ps1
│   └── .venv/                      # Generated; Git-ignored
├── SyntyLibrary/
│   ├── .gitkeep                    # Optional placeholder
│   ├── POLYGON - Adventure Pack/
│   │   ├── Preview.jpg             # Example cover at package root
│   │   └── SourceFiles.zip         # Example download
│   ├── ANIMATION - Bow Combat/
│   │   └── ...
│   ├── .synty_history.json         # Generated; Git-ignored
│   ├── .synty_sync.log             # Generated; Git-ignored
│   └── .synty_browser_profile/     # Generated browser session; Git-ignored
└── SyntyLocalDex/
    ├── build_local_dex.py          # Asset indexer
    ├── local_dex_server.py         # Local HTTP server
    ├── fbx_geometry.py             # FBX mesh preview support
    ├── local_dex_web/              # HTML, CSS, JS and viewers
    ├── rebuild_local_dex.cmd       # Index existing downloads
    ├── open_local_dex.cmd          # Start local web app
    ├── sync_and_rebuild_dex.cmd    # Downloader → indexer
    ├── tests/
    └── .localdex/                  # Generated database, catalog, preview caches; Git-ignored
```

The three directories must remain siblings, but the repository can be relocated to another drive or directory. LocalDex resolves `../SyntyLibrary` relative to its own scripts and uses `../SyntyDownloader/.venv` when available.

## 2. Quick start (Windows 11)

**Requirements:** Windows 11, internet connectivity for downloading/installing, and Python **3.10+**. The downloader uses [Playwright](https://playwright.dev/python/) and Chromium. The supplied installer can install Python through `winget` if necessary.

1. Clone or extract the repository, keeping all three folders together.
2. Double-click **`SyntyDownloader/install_synty_sync.cmd`**. It creates `.venv`, installs Python dependencies, and installs Chromium for Playwright.
3. Edit **`SyntyDownloader/config.yaml`**: set `login.email`, optional `login.password`, and `login.customer_id`. The default `output_dir: ../SyntyLibrary` points to the sibling library. `config.yaml` is Git-ignored; `config.example.yaml` is a safe tracked template.
4. Double-click **`SyntyLocalDex/sync_and_rebuild_dex.cmd`**. It runs an interactive first-package sync, then the full headless sync, then rebuilds the local catalog. The launcher sends downloads to the *sibling* `SyntyLibrary/` folder automatically.
5. Double-click **`SyntyLocalDex/open_local_dex.cmd`** and open **http://127.0.0.1:8765**. Keep its console running while using the browser; `Ctrl+C` stops the server.

For an existing downloaded library, **skip synchronization** and run `SyntyLocalDex/rebuild_local_dex.cmd` directly before opening the browser.

The `.cmd` launchers manage PowerShell execution policy with a **process-scoped** `-ExecutionPolicy Bypass` where needed; they do not permanently change the machine's settings. Organization-enforced policies may still take precedence.

## 3. SyntyDownloader — downloading and synchronization

`SyntyDownloader/synty_sync.py` uses a real Chromium browser to authenticate and navigate Synty Store pages (there is no required public download API):

- Supports interactive login, including an email-delivered one-time verification code when requested by the store.
- Reuses the saved browser profile on later runs, while the session remains valid.
- Follows paginated package lists and downloads every linked file for each package.
- Preserves the original downloaded files under `SyntyLibrary/<package name>/<filename>`; **it does not automatically extract, delete, or overwrite them**.
- Records successful download links in `.synty_history.json` so later runs can skip an existing file. Failed transfers are not marked as completed.
- Records errors and progress in `.synty_sync.log`. Incomplete transfers may remain under `.synty-partials/` for inspection.

### Run Downloader separately

From **the repository root**, with the virtual environment already installed:

```powershell
cd .\SyntyDownloader

# Validate config.yaml without opening the browser
.\.venv\Scripts\python.exe .\synty_sync.py --check-config

# Show the browser; download only the first package for verification
.\.venv\Scripts\python.exe .\synty_sync.py --limit-packages 1

# Then synchronize everything with the saved browser session
.\.venv\Scripts\python.exe .\synty_sync.py --headless
```

Add `--dry-run` to inspect packages without downloading, or use `--delay 3` to slow down requests. A new login may require another visible, interactive run before using `--headless`.

> **Configuration priority:** `config.yaml` is the single source of truth for the normal launcher. Its relative `output_dir` is resolved relative to the YAML file, not the working directory. The optional Python `--output` flag is a manual override. For compatibility with the existing Dex launcher, PowerShell still accepts `-OutputDir`, but ignores it with a warning. Keep `output_dir: ../SyntyLibrary` when using Dex’s combined launcher, which indexes the sibling library.

See [`SyntyDownloader/README_synty_sync.md`](SyntyDownloader/README_synty_sync.md) and [`SyntyDownloader/INSTALLATION_WINDOWS.md`](SyntyDownloader/INSTALLATION_WINDOWS.md) for downloader-specific details, where included.

## 4. SyntyLibrary — source of truth for downloads

Each package has its own directory, with the downloaded files left intact:

```text
SyntyLibrary/
├── POLYGON - Adventure Pack/
│   ├── Adventure_Preview.jpg
│   ├── POLYGON_Adventure_SourceFiles.zip
│   └── POLYGON_Adventure.unitypackage
└── ANIMATION - Bow Combat/
    └── ANIMATION_BowCombat.zip
```

LocalDex uses folder names and paths to **infer** collections (for example, `POLYGON` and `ANIMATION`), file types, categories and engine hints. These are heuristic labels, not guaranteed official metadata.

When a supported image (`.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`, `.avif`) exists **directly in the package directory**, LocalDex prefers the **first filename alphabetically** for the pack cover. Images inside subfolders or archives are considered fallback candidates. Root images are subject to a size limit.

**Do not commit downloaded assets.** They can be large and are associated with your account/license. The root `.gitignore` excludes `SyntyLibrary/*` while allowing `SyntyLibrary/.gitkeep` if present.

## 5. SyntyLocalDex — offline catalog and browser

LocalDex reads the folder structure and supported archive contents, then builds a catalog separate from your downloads:

```text
SyntyLocalDex/.localdex/
├── index.sqlite3       # Searchable index
├── catalog.json        # Consolidated library metadata
├── covers/             # Cached cover previews
└── fbx_thumbs/         # Generated FBX thumbnails, when supported
```

### Browser capabilities

- **Overview, Asset packs, Assets, Download files, Statistics** in the left navigation.
- Clicking a **pack card** opens that package's content, with discoverable assets and downloaded files.
- Search and filter by name/path, collection, inferred category, file type, and engine.
- Inspect an asset's source archive/path and open its location in Windows Explorer.
- Use the **Rebuild index** action in the sidebar to update the catalog.
- The **Statistics** page includes totals, collection breakdowns, type/category counts and largest packages.
- Asset cards use large thumbnails; hover over the **info icon** for the full filename with extension.

### Preview support and limitations

| Asset format | Preview behavior |
| --- | --- |
| PNG, JPG, WebP, GIF and other supported images | Image preview; animated image formats may animate. |
| MP4, WebM | Video player. |
| MP3, WAV, OGG | Audio player. |
| OBJ | Interactive geometry preview. |
| FBX (binary/ASCII, supported mesh layouts) | Interactive **static-mesh** 3D preview and generated thumbnail, including from ZIP/Unity packages. |
| Unity prefabs, Unreal engine assets, unsupported models | Indexed name/path and source details, without full native rendering. |

FBX preview is deliberately lightweight. It does **not** reproduce full materials/textures, skeletal animation, rigging, or all transforms; some FBX files cannot be rendered. For supported archive members, preview data is decompressed **on demand**, not extracted into `SyntyLibrary`. Large files are subject to safety limits.

ZIP and `.unitypackage` contents can be indexed without unpacking the whole archive. `.rar`, `.7z`, and nested archives are not exhaustively inspected. File naming conventions determine the quality of discovered asset data.

### Rebuild or run from the command line

The simplest way is to double-click:

```text
SyntyLocalDex\rebuild_local_dex.cmd
SyntyLocalDex\open_local_dex.cmd
```

Alternatively, from `SyntyLocalDex/` with Python 3.10+:

```powershell
py -3 .\build_local_dex.py
py -3 .\local_dex_server.py
```

The index is **incremental** for unchanged source files. Rebuilding can update or remove stale **catalog records**, but never deletes the original downloads. To speed up indexing large libraries, use `--skip-unity-contents` when running `build_local_dex.py` (at the cost of fewer discoverable assets).

By default, the HTTP server binds to **127.0.0.1:8765**. It is local-only, not a publicly hosted website, and it does not need Synty credentials. Keep the console open while browsing.

See [`SyntyLocalDex/README_LOCAL_DEX.md`](SyntyLocalDex/README_LOCAL_DEX.md) for component-specific notes.

## 6. Recommended daily workflow

1. Run **`SyntyLocalDex/sync_and_rebuild_dex.cmd`** to fetch new purchases and update the index in one operation.
2. Run **`SyntyLocalDex/open_local_dex.cmd`** to explore the current offline library.
3. If you add or rename files manually, use **Rebuild index** in the browser or `rebuild_local_dex.cmd`.

The downloader and indexer are independent: the browser can be used entirely offline against previously downloaded files.

## 7. Git and security

The root `.gitignore` excludes:

- Original assets under `SyntyLibrary/`, plus download history, browser profile/cookies, incomplete transfers, and logs.
- Python virtual environments and caches (`.venv/`, `__pycache__/`, `.pytest_cache/`, etc.).
- Dex-generated `.localdex/` database, metadata and preview caches.
- Temporary files, local `.env` configuration and common IDE/OS output.

Initialize and inspect the repository from its root:

```powershell
git init
git add .
git status
git commit -m "Initial Synty tooling"
```

**Important:** keep real account details in `SyntyDownloader/config.yaml`, which the repository `.gitignore` excludes. Never commit that file, the browser profile, or the download history (which may include e-mail-bearing URLs). Git ignores do not retroactively remove files that were already tracked; use `git rm --cached SyntyDownloader/config.yaml` if necessary. The Chromium profile and download history can expose account/session information and must remain private.

If any library files were tracked before adding `.gitignore`, remove them from Git's index **without deleting local files**:

```powershell
git rm -r --cached -- SyntyLibrary
git add .
git status
```

## 8. Troubleshooting

| Problem | What to check |
| --- | --- |
| Python not found | Run `SyntyDownloader/install_synty_sync.cmd`; ensure Python 3.10+ is available. |
| PowerShell refuses to run scripts | Use the provided `.cmd` launchers; they start PowerShell with process-scoped execution-policy settings. |
| Browser asks to log in again | Run the interactive downloader step; a saved session may have expired. |
| Files go to the wrong folder | Check `SyntyDownloader/config.yaml`: use `output_dir: ../SyntyLibrary` for the sibling library. The PowerShell `-OutputDir` parameter is now ignored. |
| New pack does not appear in Dex | Run `rebuild_local_dex.cmd` or **Rebuild index**. |
| No previews for some FBX files | Preview supports static mesh geometry only; not every FBX encoding, animation, or material is supported. |
| Port `8765` already in use | Close the previous LocalDex process, or start `local_dex_server.py --port 8766`. |
| Windows cannot open an asset | Check that its original download is still present in `SyntyLibrary/` and rebuild the index. |

## 9. Testing and project notes

Run the provided Python tests from the respective tool directories:

```powershell
cd .\SyntyDownloader
.\.venv\Scripts\python.exe -m unittest discover -v

cd ..\SyntyLocalDex
py -3 -m unittest discover -s tests -v
```

The download automation depends on Shopify/Sky Pilot's current HTML and authentication behavior and may need maintenance if the site changes. LocalDex is an independent, offline file-derived index, not an authoritative registry of all Synty assets. Respect the licenses and terms applicable to downloaded packs.
