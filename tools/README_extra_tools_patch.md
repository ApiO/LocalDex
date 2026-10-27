# Local Dex Extra Tools — Archive Extraction Patch

This update adds an **Extra tools** page before **Configuration** in the sidebar. It lists archive files found in the configured `SyntyLibrary` and lets you select supported archives to extract.

## Apply the patch

1. Extract the update ZIP into the root of your existing `LocalDex` repository, preserving the `SyntyLocalDex/` and `tools/` paths.
2. From the repository root, run:

   ```powershell
   py -3 tools\apply_archive_extraction_patch.py
   ```

3. Review the resulting changes with `git diff`.
4. Run the archive extraction tests and your existing Local Dex test suite.
5. Restart `launch_localdex.cmd`, then open **Extra tools** in the sidebar.

The patcher validates all expected source anchors before writing anything and stores backups of the original files in a temporary directory. It is safe to run a second time; it detects an already-installed patch.

## Behavior and safety

- The archive list is discovered from the configured local library; no archive paths are accepted from the browser.
- Supported formats: `.zip`, `.unitypackage`, `.tar`, `.tar.gz`, `.tgz`, and standalone `.gz`.
- `.rar` and `.7z` files are listed as unsupported because Local Dex uses only Python's standard library for extraction.
- Each archive is extracted to a sibling folder named after the archive (for example, `Models.zip` → `Models/`).
- Original archives are never changed or deleted.
- If the destination folder already exists, it is skipped; existing files are never overwritten.
- Archive paths that attempt traversal, and links or special filesystem entries, are rejected.
- Extracting archives is serialized against Local Dex's install/download/index jobs to avoid competing writes.
- A per-archive limit of 200 GiB uncompressed data and 200,000 entries guards against accidental oversized archives and decompression bombs.

## Files

- `SyntyLocalDex/archive_extractor.py` — safe archive discovery and extraction helpers.
- `SyntyLocalDex/tests/test_archive_extractor.py` — tests for ZIP, Unity package, GZIP, destination skipping and path traversal.
- `tools/apply_archive_extraction_patch.py` — integrates the API, page, sidebar navigation, styles and README row into the current checkout.
