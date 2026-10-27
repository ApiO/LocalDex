# Applying the Local Dex Extra Tools update

This ZIP contains a new archive-extraction module, tests, and a patcher that integrates the feature into the current GitHub checkout. It does not replace full copies of existing source files, so changes already present in your `main` branch are preserved.

1. Extract the ZIP into the repository root.
2. Run `py -3 tools\apply_archive_extraction_patch.py` from that root.
3. Review `git diff` and `git diff --check`.
4. Run `py -3 -m unittest discover -s SyntyLocalDex\tests -v`.
5. Restart `launch_localdex.cmd` and open **Extra tools**.

The page lists archives found in `SyntyLibrary`, supports selecting multiple archives, and reports extracted, skipped and failed items. Original archive files are preserved.
