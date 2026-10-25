# LocalDex — Web UI and indexer guide

This component provides the local Web UI, SQLite catalog, search and asset
previews. Start with the [root README](../README.md) for the recommended
Windows installation workflow and the full repository layout.

## Startup and paths

The repository contains three sibling directories:
`SyntyDownloader/`, `SyntyLibrary/`, and `SyntyLocalDex/`.
You can move the entire repository to another drive without rewriting paths.

- **`../install.cmd`**: install/repair Python, downloader dependencies and
  Playwright Chromium.
- **`../launch_localdex.cmd`**: start the Web UI at
  `http://127.0.0.1:8765` (default).
- **`../config.yaml`**: private account configuration and downloader
  `output_dir`, normally `SyntyLibrary`, relative to the root YAML file.
- **`rebuild_local_dex.cmd`**: optional direct index build; also available in
  **Configuration → Sync assets / Rebuild index**.
- **`sync_and_rebuild_dex.cmd`**: optional legacy combined sync/index launcher.
  It uses the downloader's root `config.yaml`.

The HTTP server and indexer use the Python standard library; downloader
operations additionally require the dependencies in
`SyntyDownloader/.venv`. The private configuration and generated caches
remain excluded from Git.

## Browser pages

| Page | Description |
| --- | --- |
| **Overview** | Browse entry point and quick access to collections. |
| **Asset packs** | Pack covers and collections; select a pack to enter Pack Explorer. |
| **Pack Explorer** | Discoverable assets and original downloaded files in Grid/List mode. Selecting an asset opens **Asset Details** without leaving the pack. |
| **Assets** | Global asset search, filters, Grid/List mode and **Asset Details**. |
| **Statistics** | Summary of counts, formats, categories, storage and large packs. |
| **Configuration** | Readiness and run history, downloader install/repair, root config editor, synchronization, index rebuild, logs and email-code authentication. |

The **Asset Details** panel appears on **Assets and Pack Explorer** and can
be resized by dragging its left border (from its default width to twice that
width). The browser remembers display mode and Light/Dark theme preferences.
Paginated asset lists automatically load more on scrolling, with a manual
**Load more** fallback.

## Index and media previews

The indexer reads `../SyntyLibrary` (or the configured library folder) and
creates generated files under **`SyntyLocalDex/.localdex/`**. This contains
an SQLite index and cached artifacts; it is not committed to Git. Indexing
and previewing do **not** delete or overwrite the downloaded source files.

Collections and categories are inferred from paths and filenames. The first
supported root-level image in a pack folder (alphabetical order) is preferred
as its cover; other candidate images can serve as fallbacks.

Supported previews include common images and animations, video/audio, OBJ and
some FBX static meshes. ZIP and Unity package contents can be inspected on
demand without extracting entire archives. FBX materials, rigging, textures
and skeletal animations may not be represented.

## Advanced CLI

From `SyntyLocalDex/` with Python 3.10+:

```powershell
py -3 .\build_local_dex.py
py -3 .\local_dex_server.py
```

The default listener is bound to **127.0.0.1**, not a public network
interface. To change the port, pass `--port 8766` to
`local_dex_server.py`. Keep the server terminal running while browsing.

### Tests

From the repository root:

```powershell
py -3 -m unittest discover -s SyntyLocalDex\tests -v
```

Real-world Synty HTML and authentication flows can change and might require
updates to the downloader. See the [downloader guide](../SyntyDownloader/README_synty_sync.md).

## License and origins

LocalDex first-party software is offered under
[GPL-3.0-only](../LICENSE) where contributors hold the necessary rights.
See [NOTICE](../NOTICE), [AI-assisted development](../docs/AI_ASSISTED_DEVELOPMENT.md),
and [third-party license notes](../docs/THIRD_PARTY_LICENSES.md). Synty
downloads and embedded third-party assets retain their original licenses.
