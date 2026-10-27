# Synty Local Dex — component guide

This is the Web UI and local search index for downloaded Synty assets. For the quickest setup and the complete repository layout, see the [root README](../README.md).
## Launch and configuration

The three folders `SyntyDownloader/`, `SyntyLibrary/` and `SyntyLocalDex/` must remain **neighbors** beneath one repository root. The parent folder can live on any drive.
- **`../install.cmd`**: prepares the downloader Python environment and Chromium (also available from the Configuration page).
- **`../launch_localdex.cmd`**: starts the local Web UI, by default at `http://127.0.0.1:8765`.
- **`../config.yaml`**: private account/login configuration and the downloader's `output_dir`, normally `SyntyLibrary`. It is ignored by Git and created/migrated by the root launchers.
- **`rebuild_local_dex.cmd`**: optional CLI index refresh; available from the Web UI through **Configuration → Sync assets / Rebuild index**.
- **`sync_and_rebuild_dex.cmd`**: optional legacy combined launcher for downloader sync followed by indexing. The downloader reads **root** `config.yaml`.
The local Web UI needs Python 3.10+; its HTTP server and indexer use the Python standard library. Downloader access from the Configuration page additionally needs Playwright, PyYAML, Chromium and the other packages installed into `SyntyDownloader/.venv`.
## Web UI features
- **Overview:** library entry point.
- **Asset packs:** browse collections and package covers, select a pack to inspect its content.
- **Pack Explorer:** browse indexed assets and downloaded files in **Grid/List** mode. Selecting an asset opens the resizeable **Asset Details** panel **without navigation away**.
- **Assets:** search all indexed asset entries and inspect details. Supports Grid/List, filters and automatic load-more on scroll.
- **Statistics:** storage, pack counts, file formats, categories and largest packages.
- **Extra tools → Extract archives:** search archive names, multi-select formats present in the library, and browse archives in collapsible package groups. The last successful extraction date is stored per archive. Re-extraction asks for confirmation, preserves identical files, keeps changed previous versions as timestamped backups, and retains files absent from the new archive. Original archives are preserved; RAR/7z are shown as unsupported.
- **Configuration:** check readiness and last-run timestamps, install/repair downloader, edit root config, sync downloads (with email-code authentication), index assets and view logs.
The navigation sidebar can be collapsed to an icon rail on desktop, with the preference saved in the browser. The root-level `../logo.png` is used for the LocalDex brand and browser icon. The side panel appears on **Assets and Pack Explorer**. It can be resized horizontally between its original width and twice that width. Display mode and Light/Dark theme choices persist in the browser.
## Index and preview behavior

The catalog is generated in `SyntyLocalDex/.localdex/` (SQLite index and cache), **not** in the downloaded library. Browsing is local. Index updates can change catalog records but never remove original download files.

The indexer infers categories and collections from folder/file naming. The first supported root-level image in a package (alphabetical order) is selected as the pack cover, with fallback candidates when no root image is available.
Images, animated images, video, audio, OBJ and supported FBX mesh previews work without unpacking complete ZIP or Unity packages. The FBX preview is limited to static mesh geometry; rigging, materials and animations might not display.
### Run directly (advanced)

```powershell
# From the SyntyLocalDex directory
py -3 .\build_local_dex.py
py -3 .\local_dex_server.py
```

The server binds to **127.0.0.1**, not the network interface. You can change the port with `--port 8766`. Keep the server console open while browsing.
## Running tests

```powershell
cd SyntyLocalDex
py -3 -m unittest discover -s tests -v
```

The downloader and Synty Store authentication can change over time; browser automation may require maintenance if Synty changes its login or downloads HTML. Asset files remain subject to their original licenses.
