# Haribol Book Distribution

Haribol Book Distribution is a Python and Streamlit app for tracking book distribution, devotee activity, and targets. It is deployed on Streamlit Community Cloud and can also be run locally on Windows, macOS, and Linux.

The app uses SQLite for its database and Google Sheets as the source for the synced book catalogue and website response data. Local SQLite data is stored on the computer running the app. Streamlit Community Cloud storage is ephemeral, so hosted app data must be backed up and should not be treated as durable storage; see [Streamlit Community Cloud deployment](#streamlit-community-cloud-deployment).

## Configuration

General app preferences are in the root `.env` file for local runs:

```dotenv
APP_NAME=Haribol_Book_Distribution
BOOK_SALES_DATA_DIR=Haribol_Book_Distribution_Data
OVERALL_POINTS_TARGET=0
OVERALL_TARGET_START_DATE=
OVERALL_TARGET_END_DATE=
FALLBACK_POINTS=1
```

`APP_NAME` controls the displayed app identity. `BOOK_SALES_DATA_DIR` is the simple local data-folder name (relative to the project unless an absolute path is intentionally configured). `OVERALL_POINTS_TARGET` is the overall dashboard target; optional `OVERALL_TARGET_START_DATE` and `OVERALL_TARGET_END_DATE` values limit its progress calculation to an inclusive date period. Leave either date blank to keep that side of the period open. Dates use `YYYY-MM-DD`. `FALLBACK_POINTS` sets points for unknown titles. These preferences are saved back to `.env` locally. Google Sheets workbook ID, tab names, and sync schedule are configurable from the app's Settings page and saved in SQLite for local runs. On Streamlit Community Cloud, use the `[app_settings]` Secrets table described below for settings that must survive restarts.

Environment variables with the same names override `.env`; Streamlit Cloud `[app_settings]` values override both environment and SQLite settings. The local `.env` file is gitignored; do not upload it. The Google Sheet is the source of truth for book variants, prices, and points. Sales and devotee targets are stored in the SQLite database for the running app instance; local runs persist on disk, while Community Cloud storage is ephemeral.

The app version is read from the newest numbered release in `CHANGELOG.md`; it is not a manually edited `.env` value. Work that has not shipped may be tracked in an `[Unreleased]` section, which does not change the displayed version. When preparing a release, run one of these from the project folder to automatically increment the version and add a dated release-history entry:

```text
python scripts/release.py feature "Describe the new feature"
python scripts/release.py fix "Describe the fix"
python scripts/release.py breaking "Describe the breaking change"
```

Use `feature` for a minor-version increment, `fix` for a patch increment, and `breaking` for a major increment. Restart the app after recording a release to display the new version.

## What is configurable?

- Read-only book catalogue and language variants synced from the Google Sheet.
- Overall points target with optional start and end dates; progress includes sales on both boundary dates and is capped at the selected analytics date.
- Individual target per devotee.
- Fallback points for unknown book titles.
- Manual point correction for a specific historical sale.
- Top 10 most active devotees, daily totals, book-by-book performance, filters, CSV exports, and prior import history.
- Category-wise daily and cumulative distribution report with a JPEG download.
- Devotee names from imports match existing names despite differences in case or extra whitespace.
- Overview comparisons against the previous day, configurable 7/30/90-day and all-time trends, average copies per sale/day, and best distribution day.

The Overview date controls the daily metrics, previous-day comparisons, trend charts, and book performance. Overall target progress uses points accumulated through the selected date, including that date. The trend period selector shows activity up to the selected date. The labeled trend charts show copies, collection received, and Shastra Daan for days with recorded sales; the book-performance chart shows copies for the top eight book and language entries. The charts are fixed rather than cursor-controlled. The **Top 10 most active devotees** list is independent of the Overview date: it aggregates sales through today, includes earlier sales, shows the latest distribution date for each devotee, and orders the most recently active devotees first.

The **Daily reports** section uses the selected Overview date for its daily totals and includes cumulative totals through that date. Both are limited to the configured overall target start and end dates; daily totals are zero if the selected date is outside that range. The report groups sales into Small Books, Medium Books, Big Books, Maha Big Books, Bhagavatam, and Caitanya Caritamrita; unrecognized categories appear under Other. Target progress respects the configured target period. Shastra Daan collected uses the `shastra_daan` total, and Total Lakshmi Collected uses the `lakshmi_transferred` total from submission summaries. The report can be downloaded as a JPEG image.

Each valid synced book-level response can represent multiple copies of one book. Website sales preserve the response sheet's reported price and points totals. Updating the catalogue does not silently rewrite historical sales.

## Technology

- Python 3.11+
- Streamlit for the hosted and local user interface
- Altair for dashboard charts
- SQLite for local storage (hosted Streamlit Community Cloud storage is ephemeral)
- pandas for tabular analytics
- Python standard library for CSV parsing, hashing, file management and database access; `google-auth` for optional Google Sheets service-account access

Dependencies are installed from PyPI during setup. A local run can work offline after dependencies are installed; the hosted app and Google Sheets sync require internet access. No external CSS or font URLs are used; the UI uses system fonts and Streamlit's built-in styling. The JPEG report uses a bundled image of the [Wikimedia Commons rupee symbol](https://commons.wikimedia.org/wiki/File:Indian_Rupee_symbol.svg), which Commons identifies as public domain.

## Setup

Install Python 3.11 or newer from https://www.python.org/downloads/.

### Windows, macOS, Linux

Open a terminal in the extracted project folder and run:

```text
python -m venv .venv
```

On some systems the command is `python3` instead of `python`:

```text
python3 -m venv .venv
```

Install packages without activating the environment:

**Windows**
```text
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe Haribol_Book_Distribution.py start
```

**macOS / Linux**
```text
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python Haribol_Book_Distribution.py start
```

The launcher starts the app in the background, binds the service to `127.0.0.1`, and disables Streamlit usage-statistics collection. Open the local URL shown in the terminal, normally:

`http://127.0.0.1:8501`

On a cold start, Streamlit may take longer to initialize; the launcher waits up to 90 seconds and reports success only after the health check passes. If startup still fails, check the application log in the data folder.

The `start` argument is optional; running the launcher with no argument also starts the app.
Start/stop control uses Python's standard library and works the same way on Windows, macOS, and Linux; it does not require PowerShell.

Stop the app from the project folder with:

**Windows**
```text
.venv\Scripts\python.exe Haribol_Book_Distribution.py stop
```

**macOS / Linux**
```text
./.venv/bin/python Haribol_Book_Distribution.py stop
```

The app log and local database are kept in `Haribol_Book_Distribution_Data`. The full storage path is not displayed in the UI. The included `scripts/start_windows.bat` and `scripts/start_macos_linux.sh` are optional convenience launchers. On macOS/Linux, if necessary, run `chmod +x scripts/start_macos_linux.sh` once.

The app interface is contained in `Haribol_Book_Distribution.py`. `streamlit_app.py` is a thin entry point for Streamlit Community Cloud. A sample-data folder is not required to run the app.

## Streamlit Community Cloud deployment

The Cloud entry point is `streamlit_app.py`; it invokes the dashboard directly instead of starting the local launcher or a second Streamlit process.

1. Push this project to a GitHub repository you can access. Do not commit `.env`, the local database, or imported sales CSVs.
2. In [Streamlit Community Cloud](https://share.streamlit.io/), create an app from that repository and select the branch and `streamlit_app.py` as the **Main file path**.
3. Deploy. The dependencies are installed from `requirements.txt`; no local launcher command is needed to open the app.
4. Choose the appropriate visibility in the Streamlit app settings and configure access there. The application itself does not provide login or role-based access.

To enable sync, create a Google service account, enable the Google Sheets API, and share the target spreadsheet with the service account's email as a Viewer. Add its credentials in Streamlit Community Cloud under **App settings → Secrets**, using TOML:

```toml
[google_service_account]
type = "service_account"
project_id = "your-google-cloud-project-id"
private_key_id = "your-private-key-id"
private_key = """-----BEGIN PRIVATE KEY-----
PASTE_THE_REMAINING_PRIVATE_KEY_LINES_HERE
-----END PRIVATE KEY-----
"""
client_email = "your-service-account@your-project.iam.gserviceaccount.com"
client_id = "your-client-id"
token_uri = "https://oauth2.googleapis.com/token"
```

Replace every example value with the corresponding value from the downloaded service-account JSON. Preserve the private key lines and delimiters. Do not commit credentials to Git or share them in screenshots or messages. For local development, create `.streamlit/secrets.toml` with the same contents and keep it out of source control.

To keep app settings across Streamlit Community Cloud restarts, add an `[app_settings]` table in the Secrets editor. These values are configuration, not credentials; replace the example spreadsheet ID with your workbook's ID:

```toml
[app_settings]
spreadsheet_id = "PASTE_YOUR_SPREADSHEET_ID"
lists_tab = "Lists"
responses_tab = "responses"
submissions_tab = "submissions"
overall_target = 0
overall_target_start_date = ""
overall_target_end_date = ""
fallback_points = 1
google_sheets_auto_sync = true
google_sheets_sync_interval_minutes = 5
google_sheets_manual_sync = true
```

Settings supplied in `[app_settings]` take precedence over SQLite and environment values and are read-only in the app; edit them in Cloud Secrets and restart the app. You can omit keys you do not want to manage there, but omitted values continue to use local storage and are not durable on Cloud. Select **Test connection** in **Settings → Google Sheets connection** to check read-only access and validate the configured tab headers. Sync actions use the service account from `[google_service_account]`. The app never writes service-account credentials to SQLite.

Set the app's visibility and access permissions to suit its audience, and restrict access to who can use or edit its Secrets. This app has no separate user accounts or roles, so dashboard users can initiate syncs; settings managed through Secrets can only be changed by someone with access to the Cloud Secrets editor. The **Response entry** page embeds the existing `books.iskw.in` form, which remains publicly accessible at its original URL regardless of dashboard visibility. Website responses are imported from the configured workbook; there is no response CSV upload page. The `Lists` tab supplies catalogue and inventory values. The `responses` tab supplies book-level rows, including book subcategory and submitted price, amount, points, and points total; these appear in **Book-level responses** and dashboard totals. The `submissions` tab supplies full-submission totals and Lakshmi/Shastra Daan values shown in **Submission summaries**. Repeated syncs update changed rows and do not duplicate them. Website sales retain the values reported in the response sheet; later catalogue changes do not rewrite historical sales.

The configured workbook tabs must have these headers (column names are case-insensitive): `Lists`: `Book Category, Book, Language, Price, Points`; `responses`: `submission_id, submitted_at, name, location, date, book_category, book_sub_category, book_name, language, quantity, price, amount, points, points_total`; `submissions`: `submission_id, submitted_at, name, location, date, total_copies, total_points, lakshmi_due, lakshmi_transferred, shastra_daan`. Lists can contain any additional columns, including `Sub Category`, and their names can change without altering the app. These required headers and all three configured tab names are checked by **Test connection**. The service account needs Viewer access to this workbook.

**Important: Community Cloud is not durable storage for this app's SQLite data.** The `[app_settings]` Secrets table can preserve the listed configuration values, but sales, devotee targets, catalogue data, and other SQLite records can be lost when the app is restarted or redeployed. Download independent backups and use durable hosted storage before relying on Cloud as the system of record. Google credentials remain in Streamlit Secrets and are separate from SQLite backups.

By default, the app performs a full sync of `Lists`, `responses`, and `submissions` immediately when the first dashboard session opens and then every 5 minutes while a dashboard session is open. Locally, configure the interval (1–1440 minutes), turn automatic sync on or off, and independently allow or disable manual sync in **Settings → Google Sheets sync schedule**. On Cloud, set durable sync options in `[app_settings]`; those values are read-only in the app. Manual full sync is available on **Response entry**; the catalogue page also offers a Lists-only refresh. Scheduled syncing pauses when there are no active dashboard sessions and resumes when a session opens. Each full sync fetches and validates all configured data before applying it in one local transaction.

## Book catalogue, prices, and points

The **Book catalogue** page displays a read-only snapshot of the configured Lists tab, including renamed or newly added columns, in sheet order. Blank column names are labeled by position and duplicate names are disambiguated for display. The snapshot uses unformatted cell values, not the sheet's visual formatting, and remains available from local SQLite until the next successful sync. Inventory cards summarize the `Stock` and `Stock Value` columns when available, matched website-response quantities, and calculated balance (stock minus matched quantities). Blank or invalid values are excluded, missing values are counted, and unmatched website responses are flagged. If either inventory column is renamed or absent, its total is unavailable rather than inferred from another column. The automatic full sync refreshes the snapshot on schedule; **Sync book list from Google Sheet** triggers an immediate Lists-only refresh when manual sync is allowed. Edit the source sheet to change the table. The app still needs the required Lists columns above for its internal catalogue and pricing: category, book, and language must be populated, book/language combinations must be unique, and prices and points must be valid non-negative numbers when populated. Prices may be currency-formatted with `₹`. There is no local catalogue editor or CSV upload/link control. The internal local catalogue mirror is not a separate source to maintain.

New form imports store the reported amount collected and Shastra Daan for each book line, plus location and remarks. These reported amounts are preserved in dashboard totals and exports. Legacy imports use the catalogue price and points per copy available when they are imported; website response totals are preserved as reported by the spreadsheet.

## Data model and modular structure

```text
Haribol_Book_Distribution/
├── Haribol_Book_Distribution.py # Launcher and Streamlit UI
├── .env                       # App name, data folder and app preferences
├── CHANGELOG.md               # Release history and current app version
├── backend/
│   └── book_sales/            # Data access and application services
│       ├── config.py          # Paths and application settings
│       ├── backup.py          # Downloadable local data backup
│       ├── db.py              # SQLite schema, indexes and initialization
│       ├── repository.py      # Common data access helpers
│       ├── catalogue.py       # Book catalogue operations
│       ├── sellers.py         # Devotee and target operations
│       ├── settings.py        # Application settings
│       ├── credentials.py    # Read-only Streamlit Secrets credential loader
│       ├── importer.py        # CSV validation, deduplication and import
│       ├── analytics.py       # Aggregations, leaderboard and exports
│       ├── report_image.py    # JPEG distribution report rendering
│       └── services.py        # Public service facade
├── requirements.txt
├── README.md
├── Haribol_Book_Distribution_Data/
│   ├── book_sales.sqlite3     # Historical sales and settings
│   ├── book_catalogue.csv     # Internal catalogue mirror
│   └── raw/                   # Imported CSV archives
└── scripts/
    ├── start_windows.bat
    ├── start_macos_linux.sh
    └── release.py             # Automatic semantic-version bump and changelog entry
```

The app opens with an expandable left-side navigation for the dashboard and management pages. The current UI version is shown in the sidebar and under **Settings → About this app**. A complete ZIP backup is available from **Settings → Data and backups**. The Overview page displays the Hare Krishna maha-mantra and the portrait stored at `assets/Srila_Prabhupada.jpeg`.

`Haribol_Book_Distribution_Data` is the local installation's storage directory for its database, catalogue mirror, and imported CSV history; it is data, not a code or sample-data folder. Existing `data/` contents are moved there automatically on first local launch when the new folder does not already exist. Streamlit Community Cloud uses instance-local storage instead, which is not durable.

## Privacy and storage behavior

- When launched locally, the app binds to `127.0.0.1`; it is not exposed to the local network by default. The Streamlit Community Cloud deployment is served by Streamlit and follows the app's configured sharing/access settings.
- The local launcher disables Streamlit usage-statistics collection. Hosted deployments are subject to the hosting platform's behavior and settings.
- The app does not use a separate cloud database or third-party analytics service. Google Sheets sync reads the configured workbook; the UI uses system fonts and inline CSS.
- Local database and imported CSV archives are stored in `Haribol_Book_Distribution_Data`. Hosted SQLite data is ephemeral and needs independent backups.
- Local app use can be offline after dependencies are installed; hosted app access and Google Sheets sync require internet connectivity.
- Do not expose a local app through port forwarding unless network access is intended.

## Backups

Use **Settings → Data and backups → Download complete data backup** to download the database, catalogue mirror, and imported CSV archives as a ZIP. The local folder is also named `Haribol_Book_Distribution_Data`; the UI does not expose its full operating-system path. Keep `.env` locally to preserve app name, storage-folder name, and app preferences; it is intentionally excluded from Git uploads.

## Scalability notes

SQLite is suitable for local use and supports indexed queries. Streamlit Community Cloud currently runs the app with instance-local SQLite storage, which is not durable across restarts or redeployments. The project separates UI, data access, catalogue, import, settings, and analytics modules so the storage layer can be adapted to a durable hosted database if required for production-scale or multi-user use.
