# Haribol_Book_Distribution

A modular, cross-platform application built with Python, Streamlit, pandas, and SQLite. It runs locally on Windows, macOS, and Linux. No Node.js, React, PowerShell, external CSS, hosted backend, or Google Cloud project is required for local/default use. Google Sheets credentials are needed only for the optional live spreadsheet sync.

The app can also be launched from Streamlit Community Cloud using `streamlit_app.py`. Cloud hosting does not make the local SQLite database durable; see [Streamlit Community Cloud deployment](#streamlit-community-cloud-deployment) before using it with real sales data.

## Configuration

All app-level configuration is in the root `.env` file:

```dotenv
APP_NAME=Haribol_Book_Distribution
BOOK_SALES_DATA_DIR=Haribol_Book_Distribution_Data
OVERALL_POINTS_TARGET=0
OVERALL_TARGET_START_DATE=
OVERALL_TARGET_END_DATE=
FALLBACK_POINTS=1
```

`APP_NAME` controls the displayed app identity. `BOOK_SALES_DATA_DIR` is the simple local data-folder name (relative to the project unless an absolute path is intentionally configured). `OVERALL_POINTS_TARGET` is the overall dashboard target; optional `OVERALL_TARGET_START_DATE` and `OVERALL_TARGET_END_DATE` values limit its progress calculation to an inclusive date period. Leave either date blank to keep that side of the period open. Dates use `YYYY-MM-DD`. `FALLBACK_POINTS` sets points for unknown titles. These settings can be updated in the UI; app-level preferences are saved back to `.env`.

Environment variables with the same names override `.env`. The local `.env` file is gitignored; do not upload it. The Google Sheet is the source of truth for book variants, prices, and points. Individual devotee targets and sales records remain in the local database.

The app version is read from the newest release in `CHANGELOG.md`; it is not a manually edited `.env` value. When preparing a release, run one of these from the project folder to automatically increment the version and add a dated release-history entry:

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
- Devotee leaderboard, daily totals, book-by-book performance, filters, CSV exports, and prior import history.
- Overview comparisons against the previous day, configurable 7/30/90-day trends, average copies per sale/day, and best distribution day.

The Overview date controls the daily metrics and book performance. Overall target progress uses points accumulated through the selected date, including that date. The trend period selector shows activity up to the selected date; the summary metrics include a previous-day comparison where available.

Each valid synced book-level response can represent multiple copies of one book. Website sales preserve the response sheet's reported price and points totals. Updating the catalogue does not silently rewrite historical sales.

## Technology

- Python 3.11+
- Streamlit for the local user interface
- SQLite for durable local storage
- pandas for tabular analytics
- Python standard library for CSV parsing, hashing, file management and database access; `google-auth` for optional Google Sheets service-account access

Dependencies are installed from PyPI during setup. After installation, normal app use does not need an internet connection; syncing the Google Sheets workbook does. No external CSS or font URLs are used; the app uses system fonts and Streamlit's built-in styling.

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

The Cloud entry point is `streamlit_app.py`. It invokes the existing dashboard directly instead of starting the local launcher or a second Streamlit process.

1. Push this project to a GitHub repository you can access. Do not commit `.env`, the local database, or imported sales CSVs.
2. In [Streamlit Community Cloud](https://share.streamlit.io/), create an app from that repository and select the branch and `streamlit_app.py` as the **Main file path**.
3. Deploy. The dependencies are installed from `requirements.txt`; no local launcher command or secrets are needed to open the app. Add the Google Sheets secret below to enable workbook sync.
4. Choose **Private** visibility in the Streamlit app settings and grant access only to approved users. The application itself does not provide login or role-based access.

To sync website submissions while keeping the response sheet private, create a Google service account, enable the Google Sheets API, and share the response spreadsheet with the service account's email as a Viewer. Add its credentials as a server-side secret in the app's **Settings → Secrets** in Streamlit Community Cloud:

```toml
[google_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-private-key-id"
private_key = """-----BEGIN PRIVATE KEY-----
your-private-key
-----END PRIVATE KEY-----
"""
client_email = "your-service-account@your-project-id.iam.gserviceaccount.com"
client_id = "your-client-id"
token_uri = "https://oauth2.googleapis.com/token"
```

The service-account credential stays on the server and is never sent to the browser. Do not paste it into source code or commit it. An API key can be used only if the workbook is public-readable; restrict that key to the Sheets API and store it in Cloud Secrets as `GOOGLE_SHEETS_API_KEY`. HTTP-referrer restrictions are not suitable for this server-to-server request. The **Response entry** page embeds the existing `books.iskw.in` form, which remains publicly accessible at its original URL even when this Streamlit app is private. Website submissions are imported with **Sync website responses**; there is no response CSV upload page. The spreadsheet's `Lists` tab supplies the live title, category, language, price, and points variants. The `responses` tab supplies book-level rows, including the submitted price, amount, points, and points total; these appear in **Book-level responses** and are also used in dashboard totals. The `submissions` tab supplies full-submission totals and Lakshmi/Shastra Daan values, shown in **Submission summaries**. Both catalogue and response data refresh on page open and every five minutes while their pages are open, or immediately with the sync button. Repeated syncs update changed rows and do not duplicate them. Website sales retain the values reported in the response sheet; later catalogue changes do not rewrite historical sales.

The workbook tabs must have these headers (column names are case-insensitive): `Lists`: `Book Category, Book, Language, Price, Points`; `responses`: `submission_id, submitted_at, name, location, date, book_category, book_name, language, quantity, price, amount, points, points_total`; `submissions`: `submission_id, submitted_at, name, location, date, total_copies, total_points, lakshmi_due, lakshmi_transferred, shastra_daan`. The service account needs Viewer access to this workbook.

**Important: Community Cloud is not durable storage for this app's data.** Sales, targets, and settings are stored in local SQLite and `.env` files; those files can be lost when the app is restarted or redeployed. The catalogue can be synced again from the source sheet, and website responses can be fetched again from the response sheet, but app-only changes do not automatically persist. Keep the source sheet and independent backups, and migrate to durable hosted storage before relying on Cloud as the system of record.

## Book catalogue, prices, and points

The **Book catalogue** page displays the title, category, language, price, and points variants synced from the spreadsheet's `Lists` tab. It refreshes automatically while the page is open and can also be refreshed with **Sync book list from Google Sheet**. This view is read-only: to add or change a title, language, price, or points value, edit the `Lists` tab in the source workbook. There is no local catalogue editor or CSV upload/link control. The app keeps an internal local catalogue mirror for its existing data and analytics services; it is not a separate source to maintain.

New form imports store the reported amount collected and Shastra Daan for each book line, plus location and remarks. These reported amounts are preserved in dashboard totals and exports. Legacy imports continue to use catalogue price and points per copy; **Refresh totals from catalogue** in the sidebar updates legacy prices without changing amounts reported by the new form.

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
│       ├── importer.py        # CSV validation, deduplication and import
│       ├── analytics.py       # Aggregations, leaderboard and exports
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

`Haribol_Book_Distribution_Data` is the app's persistent storage for its database, catalogue mirror, and imported CSV history; it is data, not a code or sample-data folder. Existing `data/` contents are moved there automatically on first launch when the new folder does not already exist.

## Privacy / local-only behavior

- The server binds to `127.0.0.1`, not `0.0.0.0`.
- Usage statistics are disabled by the launcher.
- No cloud database or third-party analytics are configured. The optional Google Sheets sync reads the configured workbook; the UI uses system fonts and inline CSS.
- The database and imported CSV archives are stored in `Haribol_Book_Distribution_Data`.
- Normal app use can be offline; syncing the Google Sheets workbook requires internet access.
- Do not expose the app through port forwarding or change the bind address if it must remain local-only.

## Backups

Use **Settings → Data and backups → Download complete data backup** to download the database, catalogue mirror, and imported CSV archives as a ZIP. The local folder is also named `Haribol_Book_Distribution_Data`; the UI does not expose its full operating-system path. Keep `.env` locally to preserve app name, storage-folder name, and app preferences; it is intentionally excluded from Git uploads.

## Scalability notes

SQLite is suitable for a single-computer, local-first app and supports indexed queries. The project separates UI, data access, catalogue, import, settings, and analytics modules so future changes can be isolated. If concurrent multi-user access or large-scale deployment becomes necessary, the repository/service layer can later be adapted to PostgreSQL and a separately hosted application; that is intentionally not part of this local-only version.
