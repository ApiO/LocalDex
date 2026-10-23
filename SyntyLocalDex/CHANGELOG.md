# Synty Local Dex — sibling-directory update

- Moved the generated index/cache default from `SyntyLibrary/.localdex` to `SyntyLocalDex/.localdex`.
- Made the library default `../SyntyLibrary`, resolved from the Dex script's directory rather than a drive-specific path or terminal's current directory.
- Updated `open_local_dex.cmd` and `rebuild_local_dex.cmd` to find Python in the sibling `SyntyDownloader/.venv`, with system Python fallbacks.
- Added `sync_and_rebuild_dex.cmd` (optional) to invoke the existing sibling downloader and then refresh the Dex index, **without editing the downloader**.
- Added an index-location override (`--index-dir`) and tests for moving the whole folder structure.
- Included only Dex-related project files, tests and documentation in this ZIP. Existing downloader configuration and downloaded files are untouched.
