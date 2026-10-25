# Third-party software and content

LocalDex's own software is offered under
[GPL-3.0-only](../LICENSE), where the contributors have the right to grant
that license. The project does not thereby relicense its dependencies or
assets downloaded from Synty Store.

## Direct Python dependencies

The downloader declares the following dependencies in
[`SyntyDownloader/synty_requirements.txt`](../SyntyDownloader/synty_requirements.txt):

| Dependency | License identified upstream | Official project |
| --- | --- | --- |
| Playwright (Python) | Apache-2.0 | https://github.com/microsoft/playwright-python |
| Beautiful Soup 4 | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| PyYAML | MIT | https://github.com/yaml/pyyaml |

These dependencies are installed separately from package repositories during
setup; they are not copied into this source repository. The dependency list
is not an exhaustive software bill of materials. Transitive dependencies,
Chromium/browser binaries, Python runtimes, and future releases may have
additional applicable licenses. Review the **actual installed/distributed
versions** and include required license notices when you redistribute them.

## Downloaded content

The `SyntyLibrary/` directory contains user-provided or account-authorized
asset downloads and is excluded from Git. Those models, textures, animations,
images, and other files remain under their **original licensors' terms**.
Neither the GPL nor this repository grants permission to redistribute them.

Screenshots of the browser and preview images can contain third-party
content. Verify permission before republishing such imagery outside the
software's own UI.

## Trademarks and AI-assisted artwork

Synty and other third-party marks are the property of their respective
owners. Visual elements generated with AI should be reviewed for similarity
to protected third-party works and applicable publication rights; an
AI-assisted image is not automatically protected by copyright.

This document records the project's present direct dependencies and
maintenance expectations; it is not a formal legal certification.
