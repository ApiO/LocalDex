# SyntyDownloader — standalone synchronization guide

SyntyDownloader uses a Playwright-controlled Chromium browser to download
files that your account is authorized to access from Synty Store. It does not
change your Synty account, delete existing downloads, or bypass MFA/CAPTCHA.
For the recommended Web UI workflow, start with the [root README](../README.md).

## What it does

- Opens `https://syntystore.com/apps/downloads/orders/<customer_id>` and
  follows the **My downloads** pagination.
- Discovers pack pages using `.sky-pilot-files-list` and downloads the files
  linked by `a.button.sky-pilot-button`.
- Supports an interactive sign-in and email verification code when required.
- Reuses a local Chromium browser profile for later runs.
- Saves files to `<output_dir>/<pack name>/<downloaded filename>` without
  extracting ZIP or Unity packages.
- Records successful download URLs/paths in `.synty_history.json`, skipping
  files already present and recorded in the history.
- Never deletes or overwrites existing asset files. When different downloads
  produce the same name, it uses a distinct filename.
- Logs failures and continues with other files where possible; interrupted
  downloads are not marked as successfully completed.

## Setup (Windows)

From the repository root:

1. Copy `config.example.yaml` to **`config.yaml`** and edit the values.
2. Run **`install.cmd`** to install or reuse Python 3.10+, create
   `SyntyDownloader/.venv`, install dependencies, and install Playwright Chromium.
3. For Web UI control, launch `launch_localdex.cmd`, open **Configuration**,
   and use **Sync downloads**.

`SyntyDownloader/synty_requirements.txt` lists Playwright, Beautiful Soup 4
and PyYAML. The installer avoids permanently changing Windows PowerShell
execution-policy settings.

### Root configuration

```yaml
# LocalDex/config.yaml — never commit account credentials
output_dir: SyntyLibrary
login:
  email: "your-email@example.com"
  password: ""  # optional; Synty may use email OTP authentication
  customer_id: "1234567890123"
```

Relative paths in `output_dir` resolve from the directory containing the
**root** `config.yaml`, regardless of the current working directory. The
standard value is `SyntyLibrary`; do not use the previous `../SyntyLibrary`
value if you have moved the YAML to the repository root.

**Where to find `customer_id`:** sign in at
[syntystore.com](https://syntystore.com/), open **My downloads**, then copy
the digits after `/apps/downloads/orders/` from the browser URL. You can also
check the `logged_in_customer_id` query parameter. Do not enter the full URL
or share private download links.

## CLI usage

Run these commands **from the repository root** after installation:

```powershell
# Validate YAML (does not launch Chromium)
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --check-config

# Discover candidate downloads without saving files
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --dry-run

# First interactive login / one pack
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --limit-packages 1

# Synchronize the full library with a saved authenticated session
.\SyntyDownloader\.venv\Scripts\python.exe .\SyntyDownloader\synty_sync.py --headless
```

`SyntyDownloader/run_synty_sync.cmd` runs an interactive one-pack sync followed
by a headless full sync. If the saved session has expired, run without
`--headless` and enter the email verification code in Chromium or the calling
interface. The old PowerShell `-OutputDir` argument remains accepted for
compatibility, but the root YAML determines the destination. An explicit
Python `--output` flag can override it for a manual one-off run.

## Output and state

```text
SyntyLibrary/
├── ANIMATION - Base Locomotion/
│   ├── archive_1.zip
│   └── archive_2.unitypackage
├── POLYGON - Adventure Pack/
│   └── adventure_pack.zip
├── .synty_history.json           # Successful download history
├── .synty_sync.log               # Operational log
├── .synty_browser_profile/      # Private Chromium login session
└── .synty-partials/             # Possible incomplete transfers
```

Actual pack and filenames are supplied by Synty Store. The downloaded files
remain in their original format. An existing nonempty file is skipped when
its entry is still present in the download history; deleting a downloaded
file lets a future run fetch it again. Existing files that are not yet in the
history might need to be fetched once to compare their content reliably.

## Safety and troubleshooting

- Do not share `config.yaml`, `.synty_browser_profile`, `.synty_history.json`
  or logs. Download URLs and profile data may contain personal/session details.
- Do not publish downloaded Synty assets; they retain their own licenses.
- If the store changes its HTML or authentication steps, selectors and login
  automation may need updating.
- Downloads are processed sequentially with a short delay; use the CLI's
  `--delay` option if you need to slow the sync further.
- The downloader does not bypass Synty access controls or rate limits.
- Interrupted transfers may leave files in `.synty-partials`; inspect/remove
  them manually only when it is safe to do so.
- Re-run the root `install.cmd` if dependencies or Chromium are missing.

Licensing of LocalDex itself and AI-assisted development disclosures are in
[LICENSE](../LICENSE), [NOTICE](../NOTICE), and
[AI-assisted development](../docs/AI_ASSISTED_DEVELOPMENT.md). These documents
do not change the licenses attached to downloaded Synty assets.
