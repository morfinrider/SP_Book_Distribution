# Haribol_Book_Distribution

A modular, cross-platform application built with Python, Streamlit, pandas, and SQLite. It runs locally on Windows, macOS, and Linux. No Node.js, React, PowerShell, external CSS, hosted backend, Google API credentials, or Google Cloud project is required.

The app can also be launched from Streamlit Community Cloud using `streamlit_app.py`. Cloud hosting does not make the local SQLite database durable; see [Streamlit Community Cloud deployment](#streamlit-community-cloud-deployment) before using it with real sales data.

## Configuration

All app-level configuration is in the root `.env` file:

```dotenv
APP_NAME=Haribol_Book_Distribution
BOOK_SALES_DATA_DIR=Haribol_Book_Distribution_Data
IMPORT_FILENAME_PATTERN=book_sales_{date}.csv
CATALOGUE_CSV_URL=
OVERALL_POINTS_TARGET=0
OVERALL_TARGET_START_DATE=
OVERALL_TARGET_END_DATE=
FALLBACK_POINTS=1
```

`APP_NAME` controls the displayed app identity. `BOOK_SALES_DATA_DIR` is the simple local data-folder name (relative to the project unless an absolute path is intentionally configured). `IMPORT_FILENAME_PATTERN` uses `{date}`, which is filled with today's date in `YYYY-MM-DD` format. `CATALOGUE_CSV_URL` stores the optional public CSV source. `OVERALL_POINTS_TARGET` is the overall dashboard target; optional `OVERALL_TARGET_START_DATE` and `OVERALL_TARGET_END_DATE` values limit its progress calculation to an inclusive date period. Leave either date blank to keep that side of the period open. Dates use `YYYY-MM-DD`. `FALLBACK_POINTS` sets points for unknown titles. These settings can be updated in the UI; app-level preferences are saved back to `.env`.

Environment variables with the same names override `.env`. The local `.env` file is gitignored; do not upload it. Book catalogue values, individual devotee targets, and sales records are business data and remain in the local database, managed from the UI.

The app version is read from the newest release in `CHANGELOG.md`; it is not a manually edited `.env` value. When preparing a release, run one of these from the project folder to automatically increment the version and add a dated release-history entry:

```text
python scripts/release.py feature "Describe the new feature"
python scripts/release.py fix "Describe the fix"
python scripts/release.py breaking "Describe the breaking change"
```

Use `feature` for a minor-version increment, `fix` for a patch increment, and `breaking` for a major increment. Restart the app after recording a release to display the new version.

## What is configurable?

- Book catalogue, price, and points per book in the Book catalogue UI (with an internal Excel-compatible CSV mirror).
- Overall points target with optional start and end dates; progress includes sales on both boundary dates and is capped at the selected analytics date.
- Individual target per devotee.
- Fallback points for unknown book titles.
- Manual point correction for a specific historical sale.
- Devotee leaderboard, daily totals, book-by-book performance, filters, CSV exports, and import history.
- Overview comparisons against the previous day, configurable 7/30/90-day trends, average copies per sale/day, and best distribution day.

The Overview date controls the daily metrics and book performance. Overall target progress uses points accumulated through the selected date, including that date. The trend period selector shows activity up to the selected date; the summary metrics include a previous-day comparison where available.

Each valid imported form response can represent multiple copies of one book. New sales store **price and points snapshots** based on the catalogue values at import time. Updating a book's price or points does not silently rewrite historical sales.

## Technology

- Python 3.11+
- Streamlit for the local user interface
- SQLite for durable local storage
- pandas for tabular analytics
- Python standard library for CSV parsing, hashing, file management and database access

Dependencies are installed from PyPI during setup. After installation, normal app use does not need an internet connection; syncing an optional hosted catalogue does. No external CSS or font URLs are used; the app uses system fonts and Streamlit's built-in styling.

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

The app interface is contained in `Haribol_Book_Distribution.py`; there is no separate frontend entry-point file. A sample-data folder is not required to run the app.

## Streamlit Community Cloud deployment

The Cloud entry point is `streamlit_app.py`. It invokes the existing dashboard directly instead of starting the local launcher or a second Streamlit process.

1. Push this project to a GitHub repository you can access. Do not commit `.env`, the local database, or imported sales CSVs.
2. In [Streamlit Community Cloud](https://share.streamlit.io/), create an app from that repository and select the branch and `streamlit_app.py` as the **Main file path**.
3. Deploy. The dependencies are installed from `requirements.txt`; no local launcher command or additional secrets are needed for the default configuration.
4. Choose the app's visibility and sharing access deliberately in the Streamlit app settings. The application itself does not provide login or role-based access.

**Important: Community Cloud is not durable storage for this app's data.** Sales, catalogue changes, targets, and settings are stored in local SQLite and `.env` files; those files can be lost when the app is restarted or redeployed. The app starts with a new database if no database file is present. Do not use this deployment for live records or as the only copy of business data. Before relying on it, migrate the database and settings to durable hosted storage and verify backups and access controls. Local backups do not automatically sync to Cloud.

## Google Form setup

Create questions for the distribution date, distributor, location, book entries, collection summary, total Shastra Daan, total books distributed, and optional remarks. In **Books Distributed**, require one entry per line in this format:

```text
BookCode | Quantity | AmountCollected | ShastraDaan
BG | 1 | 100 | 250
SSR | 2 | 300 | 0
KB | 1 | 500 | 0
```

Use the short codes configured in the app's Book catalogue. Amounts are totals for each book line, not per-copy amounts. The app checks the entry totals against Total Collection Received, Total Shastra Daan, and Total Books Distributed.

Link responses to a Google Sheet. Each submission can contain multiple book lines. Export the response sheet/tab as CSV and import it through the app. The app does not connect to Google's API.

Keep short codes aligned with the active titles in the app's Book catalogue. The form's book-code reference can list commonly used codes; the full catalogue remains managed in the app.

## Daily CSV naming

The default name is `book_sales_YYYY-MM-DD.csv`, for example `book_sales_2026-10-25.csv`. Change the pattern in Settings or `.env` if you prefer a different convention.

The application archives the uploaded CSV under the configured daily filename in the local data folder. If that filename already exists, it adds a numeric suffix. Duplicate prevention uses the timestamp, devotee, sale date, book, and (for coded entries) line position. Re-importing the complete response sheet skips previously seen submissions and adds new ones; older sales remain stored in SQLite. The import result calls out duplicate-only imports and rejected rows; review and correct rejected rows before relying on dashboard totals. On the Overview tab, select a date to see that day's totals and devotee rankings; it defaults to today. After importing a CSV, select **Refresh dashboard** in the sidebar to return to the Overview with the latest saved data.

Google Forms timestamps are important for distinguishing two legitimate submissions of the same book by the same person on the same date. Keep the Timestamp column in the CSV. For slash-separated dates in legacy imports, the importer infers day-first or month-first ordering from unambiguous dates in the same CSV; if all dates are ambiguous, it retains the month-first default. Coded-book form dates use day-first ordering.

## CSV columns

The new form's export includes Timestamp, Distribution Date, Distributor, Location, Books Distributed, Total Collection Received, Total Shastra Daan, Total Books Distributed, and Remarks. The importer also continues to support legacy exports containing Devotee, Date of Sale, Book Sold, and Quantity columns.

For legacy response CSVs without a Quantity column, each row is treated as quantity 1. Grid-style legacy exports are also supported when columns are active book titles and populated cells contain positive whole-number quantities.

Downloaded sales and import-history CSVs escape formula-leading text, including values preceded by whitespace or control characters. Numeric values remain numeric in the export.

Imported devotee names are added to the devotee directory automatically when needed, so they appear in the leaderboard without needing to be entered separately.

Supported dates include M/D/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD/MM/YYYY, and DD-MMM-YYYY (for example, 25-Oct-2026). Slash-separated date ordering is inferred from unambiguous dates in the same CSV; the coded-book form uses day-first ordering.

## Book catalogue, prices, and points

Edit books, short codes, tags, prices, points, and active status in the **Book catalogue** page. Codes are unique, case-insensitive, and used to identify books in form entries. Tags can be free text such as small book, medium book, or big book. Changes are saved to the local database and mirrored to an internal CSV; there is no need to locate or edit that file manually. The CSV uses these columns:

```csv
book_name,code,book_tag,price,points
Bhagavad Gita,BG,big book,0.00,1
Krishna Book,KB,big book,0.00,1
Srimad Bhagavatam,SB,big book,0.00,1
```

Price and points are entered per copy; both support decimal values (for example, 1.25 points). The application creates or updates this file from the catalogue stored locally.

To update several titles at once, expand **Upload catalogue CSV** in the Book catalogue page and upload a UTF-8 CSV (up to 2 MB) with book name and price columns. Column names may be `book_name`/`book`/`title` and `price`/`price per copy`/`MRP`. Points, code, and book tag columns are optional. The import merges rows: it adds new books and updates matching titles, while leaving unlisted books active. Existing codes, tags, and points are preserved when the CSV omits them or leaves them blank; new books default to 1 point per copy. After import, add missing short codes or tags in the catalogue editor.

To sync from a hosted catalogue, open **Settings → Connect a book catalogue CSV**, paste a public HTTPS link to a CSV containing `book_name`, `price`, and `points`, and optionally `code` and `book_tag`, then select **Save link and sync catalogue**. The backend validates and downloads the CSV (UTF-8, up to 2 MB); titles omitted from the linked catalogue are deactivated. If the optional columns are omitted, existing codes and tags are retained. Use a Google Sheets CSV export link, not a link to the regular spreadsheet webpage.

New form imports store the reported amount collected and Shastra Daan for each book line, plus location and remarks. These reported amounts are preserved in dashboard totals and exports. Legacy imports continue to use catalogue price and points per copy; **Refresh totals from catalogue** in the sidebar updates legacy prices without changing amounts reported by the new form.

## Data model and modular structure

```text
Haribol_Book_Distribution/
├── Haribol_Book_Distribution.py # Launcher and Streamlit UI
├── .env                       # App name, data folder and CSV settings
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
- No cloud database or third-party analytics are configured. An optional catalogue sync fetches only the public HTTPS CSV URL explicitly supplied in Settings; the UI uses system fonts and inline CSS.
- The database and imported CSV archives are stored in `Haribol_Book_Distribution_Data`.
- Normal app use can be offline; syncing a hosted catalogue requires internet access.
- Do not expose the app through port forwarding or change the bind address if it must remain local-only.

## Backups

Use **Settings → Data and backups → Download complete data backup** to download the database, catalogue mirror, and imported CSV archives as a ZIP. The local folder is also named `Haribol_Book_Distribution_Data`; the UI does not expose its full operating-system path. Keep `.env` locally to preserve app name, storage-folder name, and CSV settings; it is intentionally excluded from Git uploads.

## Scalability notes

SQLite is suitable for a single-computer, local-first app and supports indexed queries. The project separates UI, data access, catalogue, import, settings, and analytics modules so future changes can be isolated. If concurrent multi-user access or large-scale deployment becomes necessary, the repository/service layer can later be adapted to PostgreSQL and a separately hosted application; that is intentionally not part of this local-only version.
