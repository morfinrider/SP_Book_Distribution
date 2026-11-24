# Release history

## [Unreleased]

- Make dashboard charts larger, labeled, and stationary, using bars for daily values

## [1.12.0] - 2026-11-24

- Restore catalogue inventory summary cards alongside the flexible Lists table
- Display the synced Lists tab as a read-only table that follows renamed and added columns
- Fix rupee symbol rendering in downloadable distribution reports across platforms

## [1.11.0] - 2026-11-22

- Show the 10 most recently active devotees with cumulative sales through today, ordered by latest distribution date
- Add daily and cumulative category distribution reports, bounded by configured target dates, with a JPEG download
- Match imported devotee names without regard to case or excess whitespace
- Update the README for the hosted Streamlit app and clarify local versus hosted storage behavior

## [1.10.0] - 2026-11-16

- Read the configured spreadsheet URL from service-account secrets for catalogue, response, and submission syncs, with a built-in fallback
- Accept rupee-formatted catalogue prices from spreadsheet CSV exports
- Expand the dashboard layout to prevent page headings and descriptions from clipping
- Update dashboard branding, About text, and server-storage wording for hosted use

## [1.9.0] - 2026-11-13

- Add a Streamlit Community Cloud entry point and deployment guidance
- Embed the IBC Sarjapur entry form and sync the live `Lists`, `responses`, and `submissions` workbook tabs
- Display book-level responses and submission summaries, preserving sheet-reported prices, amounts, points, and totals
- Support private Google Sheets access with server-side service-account credentials
- Remove the response CSV upload page; website responses sync directly from the workbook
- Make the spreadsheet the only catalogue source in the UI; remove local editing, book creation, catalogue CSV controls, and historical price refresh action

## [1.8.0] - 2026-11-12

- Add optional, inclusive start and end dates for overall target progress
- Escape formula-leading text in downloadable sales and import-history CSVs
- Clarify duplicate-only and rejected-row CSV import results
- Ignore local `.env` settings in Git

## [1.7.0] - 2026-11-01

- Support coded book-line entries, book tags, reported collection and Shastra Daan
- Validate submission totals and refresh dashboard donation metrics
- Apply a coordinated color palette to dashboard charts
- Add merge-based CSV catalogue upload for book names, prices, and optional metadata

## [1.6.1] - 2026-10-25

- Give distribution trend charts a dedicated full-width row

## [1.6.0] - 2026-10-25

- Expand dashboard with daily comparisons and distribution insights

## [1.5.0] - 2026-10-25

- Add devotee analytics and refresh historical prices from the catalogue

## [1.4.1] - 2026-10-25

- Recognize Devotee sales uploads and show import results

## [1.4.0] - 2026-10-25

- Support fractional point values and improve cold-start reliability

## [1.3.0] - 2026-10-25

- Replaced the Overview subtitle with the requested book-distribution quote

## [1.2.0] - 2026-10-25

- Added the local Srila Prabhupada portrait and book icon

## [1.1.0] - 2026-10-25

- Added the Hare Krishna maha-mantra to Overview and automated semantic-version releases

## [1.0.0] - 2026-10-25

- Initial local-first book distribution dashboard release.
