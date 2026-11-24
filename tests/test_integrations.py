import csv
import io
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from book_sales import integrations
from book_sales import catalogue
from book_sales import analytics
from book_sales.db import SCHEMA


class IntegrationTests(unittest.TestCase):
    def test_distribution_catalogue_groups_languages_by_title(self):
        parsed = integrations.parse_distribution_catalogue_csv(
            b"Book Category,Book,Language,Price,Points\n"
            b"Big Book,Title A,English,280,2\n"
            b"Big Book,Title A,Kannada,,2\n"
            b"Small Books,Title B,Hindi,,0.25\n"
        )
        self.assertEqual(
            parsed,
            [
                (
                    "Title A", "Big Book", "English", 280.0, 2.0, "",
                    *([None] * 13),
                ),
                (
                    "Title A", "Big Book", "Kannada", None, 2.0, "",
                    *([None] * 13),
                ),
                (
                    "Title B", "Small Books", "Hindi", None, 0.25, "",
                    *([None] * 13),
                ),
            ],
        )

    def test_distribution_catalogue_accepts_rupee_formatted_prices(self):
        parsed = integrations.parse_distribution_catalogue_csv(
            "Book Category,Book,Language,Price,Points\n"
            'Big Book,Title A,English,"₹1,280.00",2\n'.encode("utf-8")
        )
        self.assertEqual(
            parsed,
            [
                (
                    "Title A", "Big Book", "English", 1280.0, 2.0, "",
                    *([None] * 13),
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "Price must be a number"):
            integrations.parse_distribution_catalogue_csv(
                "Book Category,Book,Language,Price,Points\n"
                'Big Book,Title A,English,"₹not-a-number",2\n'.encode("utf-8")
            )

    def test_distribution_catalogue_parses_inventory_columns_and_allotted_alias(self):
        headers = list(integrations._LISTS_HEADERS)
        headers[16] = "Allotted Boks Amt"
        row = [
            "Big Book",
            "Small Books",
            "Title A",
            "English",
            "280",
            "2",
            "5",
            "500",
            "3",
            "2",
            "250",
            "1",
            "100",
            "2",
            "150",
            "4",
            "400",
            "1",
            "100",
        ]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerow(row)

        parsed = integrations.parse_distribution_catalogue_csv(
            output.getvalue().encode("utf-8")
        )

        self.assertEqual(
            parsed,
            [
                (
                    "Title A",
                    "Big Book",
                    "English",
                    280.0,
                    2.0,
                    "Small Books",
                    5.0,
                    500.0,
                    3.0,
                    2.0,
                    250.0,
                    1.0,
                    100.0,
                    2.0,
                    150.0,
                    4.0,
                    400.0,
                    1.0,
                    100.0,
                )
            ],
        )

        row[6] = "-1"
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerow(row)
        with self.assertRaisesRegex(ValueError, "Stock must be finite and non-negative"):
            integrations.parse_distribution_catalogue_csv(
                output.getvalue().encode("utf-8")
            )

    def test_inventory_summary_uses_known_values_and_reports_missing_rows(self):
        self.assertEqual(
            catalogue.summarize_inventory_values(pd.Series([5.0, None, 3.0])),
            (8.0, 2, 3),
        )
        self.assertEqual(
            catalogue.summarize_inventory_values(pd.Series([None, None])),
            (None, 0, 2),
        )
        self.assertEqual(
            catalogue.summarize_inventory_values(pd.Series([0.0, None])),
            (0.0, 1, 2),
        )

    def test_catalogue_inventory_uses_matched_website_responses(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript(
            """
            CREATE TABLE books (id INTEGER PRIMARY KEY, book_name TEXT, active INTEGER);
            CREATE TABLE book_variants (
                id INTEGER PRIMARY KEY, book_id INTEGER, book_category TEXT,
                book_sub_category TEXT, language TEXT, price REAL, points REAL,
                stock REAL, stock_value REAL, books_distributed REAL,
                balance_books REAL, amount_collected REAL, books_billed REAL,
                billed_amount REAL, books_unbilled REAL, unbilled_amount REAL,
                allotted_books REAL, allotted_books_amt REAL, ibc_s_stock REAL,
                ibc_s_stock_amt REAL, active INTEGER, updated_at TEXT
            );
            CREATE TABLE sales (
                book_name TEXT, language TEXT, quantity INTEGER,
                external_submission_id TEXT
            );
            INSERT INTO books VALUES (1, 'Title A', 1);
            INSERT INTO book_variants VALUES (
                1, 1, 'Big Book', '', 'English', 10, 1, 100, 1000,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, ''
            );
            INSERT INTO book_variants VALUES (
                2, 1, 'Big Book', '', 'Hindi', 10, 1, 50, 500,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, ''
            );
            INSERT INTO sales VALUES ('title a', 'english', 3, 'web-1');
            INSERT INTO sales VALUES ('Title A', 'English', 4, 'web-2');
            INSERT INTO sales VALUES ('Title A', 'English', 20, '');
            INSERT INTO sales VALUES ('Unknown title', 'English', 2, 'web-3');
            """
        )

        def read_query(sql, params=()):
            return pd.read_sql_query(sql, connection, params=params)

        try:
            with patch.object(catalogue, "query_df", side_effect=read_query):
                variants = catalogue.list_book_variants(
                    include_response_totals=True
                )
                unmatched = catalogue.unmatched_website_response_totals()

            english = variants.set_index("language").loc["English"]
            hindi = variants.set_index("language").loc["Hindi"]
            self.assertEqual(english["books_distributed"], 0)
            self.assertEqual(english["response_books_distributed"], 7)
            self.assertEqual(english["response_balance_books"], 93)
            self.assertEqual(hindi["response_books_distributed"], 0)
            self.assertEqual(hindi["response_balance_books"], 50)
            self.assertEqual(unmatched, (1, 2))
        finally:
            connection.close()

    def test_catalogue_sync_reads_configured_lists_tab_with_api_key(self):
        values = [
            ["Book Category", "Book", "Language", "Price", "Points"],
            ["Big Book", "Title A", "English", 280, 2],
        ]
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        with (
            patch.object(
                integrations,
                "_fetch_sheet_values",
                return_value=values,
            ) as fetch,
            patch.object(integrations, "connect", return_value=connection),
            patch.object(integrations, "_write_catalogue_file"),
        ):
            spreadsheet_config = {
                "spreadsheet_id": "configured-sheet",
                "lists_tab": "Book Lists",
                "responses_tab": "responses",
                "submissions_tab": "submissions",
            }
            result = integrations.sync_distribution_catalogue(
                "test-key",
                spreadsheet_config=spreadsheet_config,
            )

        fetch.assert_called_once_with(
            "'Book Lists'",
            "Lists",
            "test-key",
            None,
            spreadsheet_config,
        )
        self.assertEqual(result["added"], 1)
        self.assertEqual(
            connection.execute("SELECT price, default_points FROM books").fetchone()[:],
            (280.0, 2.0),
        )
        connection.close()

    def test_lists_snapshot_tracks_renamed_and_new_columns(self):
        headers = [
            "Book Category", "Sub Category", "Book", "Language", "Price", "Points",
            "Stock", "Stock Value", "Books Distributed", "Amount Collected",
            "Books Billed", "Billed Amount", "Books Unbilled", "Unbilled Amount",
            "Allotted Books", "Allotted Boks Amt", "Available Stock",
            "Available Stock Amt", "New field", "Another field",
        ]
        values = [
            headers,
            ["Big Book", "", "Title A", "English", 280, 2, 10, 2800, 4,
             1000, 1, 280, 3, 720, 1, 280, 6, 1680, "note", 0],
        ]
        changed = [headers + ["Added later"], values[1] + ["new value"]]

        class FakeResponse:
            def __init__(self, sheet_values):
                self.sheet_values = sheet_values

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps({"values": self.sheet_values}).encode("utf-8")

        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        try:
            with (
                patch.object(integrations, "connect", return_value=connection),
                patch.object(integrations, "_write_catalogue_file"),
                patch.object(
                    integrations.urllib.request, "urlopen",
                    side_effect=[FakeResponse(values), FakeResponse(changed)],
                ) as fetch,
            ):
                config = {"spreadsheet_id": "test-sheet", "lists_tab": "Lists"}
                integrations.sync_distribution_catalogue("test-key", spreadsheet_config=config)
                first = integrations.get_lists_snapshot()
                self.assertEqual(list(first.columns), headers)
                self.assertEqual(first.iloc[0]["Available Stock"], "6")
                self.assertEqual(first.iloc[0]["Another field"], "0")

                integrations.sync_distribution_catalogue("test-key", spreadsheet_config=config)
                updated = integrations.get_lists_snapshot()
                self.assertEqual(list(updated.columns), headers + ["Added later"])
                self.assertEqual(updated.iloc[0]["Added later"], "new value")
                self.assertIn("/values/%27Lists%27?", fetch.call_args.args[0].full_url)
        finally:
            connection.close()

    def test_lists_sync_rejects_missing_or_duplicate_core_headers(self):
        for headers in (
            ["Book Category", "Language", "Price", "Points"],
            ["Book Category", "Book", "BOOK", "Language", "Price", "Points"],
        ):
            with self.subTest(headers=headers):
                with patch.object(integrations, "_fetch_sheet_values", return_value=[headers]):
                    with self.assertRaisesRegex(ValueError, "missing required columns|duplicate required columns"):
                        integrations._fetch_distribution_catalogue(
                            "test-key", spreadsheet_config={"lists_tab": "Lists"}
                        )

    def test_full_sync_saves_lists_snapshot(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        values = [["Book", "Available Stock"], ["Title", 7]]
        try:
            with (
                patch.object(integrations, "connect", return_value=connection),
                patch.object(integrations, "_write_catalogue_file"),
                patch.object(integrations, "get_settings", return_value={"fallback_points": "1"}),
                patch.object(integrations, "fetch_response_sheet", return_value=[]),
                patch.object(integrations, "fetch_submission_sheet", return_value=[]),
                patch.object(
                    integrations, "_fetch_distribution_catalogue",
                    return_value=([("Title", "Big Book", "English", 50.0, 1.0)], values),
                ),
            ):
                integrations.sync_distribution_responses("test-key", spreadsheet_config={"lists_tab": "Lists"})
                snapshot = integrations.get_lists_snapshot()
                self.assertEqual(list(snapshot.columns), ["Book", "Available Stock"])
                self.assertEqual(snapshot.iloc[0]["Available Stock"], "7")
        finally:
            connection.close()

    def test_full_sync_feeds_sales_and_dashboard_with_renamed_lists_columns(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        lists = [
            ["Book Category", "Sub Category", "Book", "Language", "Price", "Points",
             "Available Stock", "Available Stock Amt"],
            ["Big Book", "", "Title A", "English", 50, 2, 6, 300],
        ]
        responses = [
            ["submission_id", "submitted_at", "name", "location", "date",
             "book_category", "book_sub_category", "book_name", "language",
             "quantity", "price", "amount", "points", "points_total"],
            ["sub-1", "2026-11-18T10:00:00Z", "Devotee", "Sarjapur", "2026-11-18",
             "Big Book", "", "Title A", "English", 2, 45, 90, 2, 4],
        ]
        submissions = [
            ["submission_id", "submitted_at", "name", "location", "date", "total_copies",
             "total_points", "lakshmi_due", "lakshmi_transferred", "shastra_daan"],
            ["sub-1", "2026-11-18T10:00:00Z", "Devotee", "Sarjapur", "2026-11-18",
             2, 4, 90, 80, 10],
        ]

        class FakeResponse:
            def __init__(self, values):
                self.values = values

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps({"values": self.values}).encode("utf-8")

        def read_query(sql, params=()):
            return pd.read_sql_query(sql, connection, params=params)

        settings = {"fallback_points": "1", "overall_target": "0"}
        config = {
            "spreadsheet_id": "test-sheet", "lists_tab": "Lists",
            "responses_tab": "responses", "submissions_tab": "submissions",
        }
        try:
            with (
                patch.object(integrations, "connect", return_value=connection),
                patch.object(integrations, "_write_catalogue_file"),
                patch.object(integrations, "get_settings", return_value=settings),
                patch.object(analytics, "get_settings", return_value=settings),
                patch.object(analytics, "query_df", side_effect=read_query),
                patch.object(
                    integrations.urllib.request, "urlopen",
                    side_effect=[
                        FakeResponse(values)
                        for values in (responses, submissions, lists) * 2
                    ],
                ),
            ):
                first = integrations.sync_distribution_responses("test-key", spreadsheet_config=config)
                second = integrations.sync_distribution_responses("test-key", spreadsheet_config=config)
                self.assertEqual((first["added"], second["duplicates"]), (1, 1))
                self.assertEqual((first["submissions_added"], second["submissions_unchanged"]), (1, 1))
                sales = analytics.list_sales()
                self.assertEqual(len(sales), 1)
                self.assertEqual((sales.iloc[0]["amount_collected"], sales.iloc[0]["total_points"]), (90, 4))
                summary = analytics.dashboard_summary("2026-11-18")
                self.assertEqual((summary["books_sold"], summary["points"], summary["revenue"]), (2, 4, 90))
                self.assertEqual(analytics.leaderboard(sale_date="2026-11-18").iloc[0]["books_sold"], 2)
                report = analytics.distribution_report("2026-11-18")
                self.assertEqual((report["daily_total_copies"], report["total_lakshmi_collected"]), (2, 80))
                self.assertEqual(report["shastra_daan_collected"], 10)
                self.assertEqual(integrations.get_lists_snapshot().iloc[0]["Available Stock"], "6")
        finally:
            connection.close()

    def test_catalogue_and_snapshot_rollback_together_on_storage_error(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        values = [
            ["Book Category", "Book", "Language", "Price", "Points"],
            ["Big Book", "Title", "English", 50, 1],
        ]
        try:
            with (
                patch.object(integrations, "connect", return_value=connection),
                patch.object(integrations, "_fetch_sheet_values", return_value=values),
                patch.object(
                    integrations, "_save_lists_snapshot",
                    side_effect=sqlite3.OperationalError("storage failure"),
                ),
            ):
                with self.assertRaisesRegex(sqlite3.OperationalError, "storage failure"):
                    integrations.sync_distribution_catalogue(
                        "test-key", spreadsheet_config={"lists_tab": "Lists"}
                    )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM books").fetchone()[0], 0)
        finally:
            connection.close()

    def test_spreadsheet_id_accepts_id_or_google_sheets_url(self):
        self.assertEqual(
            integrations._spreadsheet_id(
                {
                    "spreadsheet_id": (
                        "https://docs.google.com/spreadsheets/d/"
                        "configured-sheet_id/edit"
                    )
                }
            ),
            "configured-sheet_id",
        )
        self.assertEqual(
            integrations._spreadsheet_id({"spreadsheet_id": "configured_sheet-id"}),
            "configured_sheet-id",
        )
        with self.assertRaisesRegex(ValueError, "spreadsheet ID or URL is required"):
            integrations._spreadsheet_id({"spreadsheet_id": ""})

    def test_spreadsheet_id_rejects_non_google_sheets_urls(self):
        with self.assertRaisesRegex(ValueError, "valid Google Sheets URL"):
            integrations._spreadsheet_id(
                {"spreadsheet_id": "https://example.com/spreadsheets/d/sheet-id/edit"}
            )

    def test_connection_test_checks_all_configured_tabs_read_only(self):
        spreadsheet_config = {
            "spreadsheet_id": "configured-sheet",
            "lists_tab": "Books",
            "responses_tab": "Website responses",
            "submissions_tab": "Summary",
        }
        with patch.object(
            integrations,
            "_fetch_sheet_records",
            return_value=[],
        ) as fetch:
            result = integrations.test_google_sheets_connection(
                service_account_info={"type": "service_account"},
                spreadsheet_config=spreadsheet_config,
            )

        self.assertEqual(
            result,
            {
                "spreadsheet_id": "configured-sheet",
                "tabs": ["Books", "Website responses", "Summary"],
            },
        )
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(
            fetch.call_args_list[0].args[1],
            integrations._LISTS_REQUIRED_HEADERS,
        )
        self.assertIn("booksubcategory", fetch.call_args_list[1].args[1])
        self.assertEqual(
            fetch.call_args_list[0].args[0],
            "'Books'!1:1",
        )
        self.assertEqual(
            fetch.call_args_list[1].args[0],
            "'Website responses'!A1:N1",
        )
        self.assertEqual(
            fetch.call_args_list[2].args[0],
            "'Summary'!A1:J1",
        )

    def test_connection_test_reports_tabs_reached_before_failure(self):
        spreadsheet_config = {
            "spreadsheet_id": "configured-sheet",
            "lists_tab": "Books",
            "responses_tab": "Wrong responses tab",
            "submissions_tab": "Summary",
        }
        with patch.object(
            integrations,
            "_fetch_sheet_records",
            side_effect=[[], ValueError("missing required columns")],
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Tabs reached before failure: Books. missing required columns",
            ):
                integrations.test_google_sheets_connection(
                    service_account_info={"type": "service_account"},
                    spreadsheet_config=spreadsheet_config,
                )

    def test_catalogue_sync_updates_variant_prices_and_points(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY, book_name TEXT UNIQUE, book_tag TEXT,
                languages TEXT, default_points REAL, price REAL, active INTEGER,
                created_at TEXT, updated_at TEXT
            );
            CREATE TABLE book_variants (
                id INTEGER PRIMARY KEY, book_id INTEGER, language TEXT COLLATE NOCASE,
                book_category TEXT, book_sub_category TEXT, price REAL, points REAL,
                stock REAL, stock_value REAL, books_distributed REAL,
                balance_books REAL, amount_collected REAL, books_billed REAL,
                billed_amount REAL, books_unbilled REAL, unbilled_amount REAL,
                allotted_books REAL, allotted_books_amt REAL, ibc_s_stock REAL,
                ibc_s_stock_amt REAL, active INTEGER,
                updated_at TEXT, UNIQUE(book_id, language)
            );
            """
        )
        inventory = [
            5.0, 500.0, 3.0, 2.0, 250.0, 1.0, 100.0,
            2.0, 150.0, 4.0, 400.0, 1.0, 100.0,
        ]
        rows = [
            ("Title A", "Big Book", "English", 280.0, 2.0, "Small Books", *inventory),
            ("Title A", "Big Book", "Kannada", None, 2.0, "Small Books", *inventory),
        ]
        try:
            with (
                patch.object(catalogue, "connect", return_value=connection),
                patch.object(catalogue, "_write_catalogue_file"),
            ):
                initial = catalogue.merge_distribution_catalogue(rows)
                unchanged = catalogue.merge_distribution_catalogue(rows)
                updated = catalogue.merge_distribution_catalogue(
                    [
                        ("Title A", "Big Book", "English", 300.0, 3.0, "Small Books", *inventory),
                        ("Title A", "Big Book", "Kannada", None, 2.0, "Small Books", *inventory),
                    ]
                )
            variants = connection.execute(
                "SELECT language, price, points, book_sub_category, stock, "
                "stock_value, ibc_s_stock_amt FROM book_variants ORDER BY language"
            ).fetchall()
            self.assertEqual(initial["variants_added"], 2)
            self.assertEqual(unchanged["variants_updated"], 0)
            self.assertEqual(updated["variants_updated"], 2)
            self.assertEqual(
                [tuple(row) for row in variants],
                [
                    ("English", 300.0, 3.0, "Small Books", 5.0, 500.0, 100.0),
                    ("Kannada", 300.0, 2.0, "Small Books", 5.0, 500.0, 100.0),
                ],
            )
        finally:
            connection.close()

    def test_response_sheet_fetch_uses_api_key_and_parses_header_rows(self):
        payload = {
            "values": [
                [
                    "submission_id",
                    "submitted_at",
                    "name",
                    "location",
                    "date",
                    "book_category",
                    "book_sub_category",
                    "book_name",
                    "language",
                    "quantity",
                    "price",
                    "amount",
                    "points",
                    "points_total",
                ],
                [
                    "sub-1",
                    "2026-11-13T10:00:00Z",
                    "Devotee",
                    "",
                    "2026-11-13",
                    "Big Book",
                    "Small books",
                    "Title",
                    "English",
                    "2",
                    "50",
                    "100",
                    "2",
                    "4",
                ],
            ]
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps(payload).encode("utf-8")

        with patch.object(
            integrations.urllib.request,
            "urlopen",
            return_value=FakeResponse(),
        ) as urlopen:
            rows = integrations.fetch_response_sheet(
                "test-key",
                spreadsheet_config={
                    "spreadsheet_id": "configured-sheet",
                    "lists_tab": "Lists",
                    "responses_tab": "responses",
                    "submissions_tab": "submissions",
                },
            )

        self.assertEqual(rows[0]["submissionid"], "sub-1")
        self.assertEqual(rows[0]["bookname"], "Title")
        self.assertEqual(rows[0]["booksubcategory"], "Small books")
        self.assertIn("key=test-key", urlopen.call_args.args[0].full_url)

    def test_sheet_fetch_uses_resolved_spreadsheet_id(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps({"values": [["submission_id"]]}).encode("utf-8")

        with (
            patch.object(
                integrations,
                "_spreadsheet_id",
                return_value="configured-sheet",
            ),
            patch.object(
                integrations.urllib.request,
                "urlopen",
                return_value=FakeResponse(),
            ) as urlopen,
        ):
            rows = integrations._fetch_sheet_records(
                "responses!A:N",
                set(),
                "responses",
                api_key="test-key",
            )

        self.assertEqual(rows, [])
        self.assertIn(
            "/configured-sheet/values/responses!A:N",
            urlopen.call_args.args[0].full_url,
        )

    def test_sheet_fetch_surfaces_google_403_details(self):
        response_body = json.dumps(
            {"error": {"message": "The caller does not have permission"}}
        ).encode("utf-8")
        http_error = integrations.urllib.error.HTTPError(
            "https://sheets.googleapis.com/",
            403,
            "Forbidden",
            {},
            io.BytesIO(response_body),
        )
        with patch.object(
            integrations.urllib.request,
            "urlopen",
            side_effect=http_error,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "shared with the service-account email as Viewer",
            ) as context:
                integrations._fetch_sheet_records(
                    "responses!A:N",
                    set(),
                    "responses",
                    api_key="test-key",
                    spreadsheet_config={
                        "spreadsheet_id": "configured-sheet",
                        "lists_tab": "Lists",
                        "responses_tab": "responses",
                        "submissions_tab": "submissions",
                    },
                )

        self.assertIn(
            "The caller does not have permission",
            str(context.exception),
        )
        self.assertIn("Google Sheets API is enabled", str(context.exception))

    def test_response_import_is_idempotent_and_preserves_language(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE sellers (
                seller_name TEXT PRIMARY KEY, active INTEGER, created_at TEXT
            );
            CREATE TABLE sales (
                row_key TEXT UNIQUE, form_timestamp TEXT, seller_name TEXT,
                sale_date TEXT, book_name TEXT, language TEXT, book_category TEXT,
                book_sub_category TEXT, external_submission_id TEXT, location TEXT,
                remarks TEXT, points REAL, quantity INTEGER, unit_price REAL,
                amount_collected REAL, shastra_daan REAL,
                reported_points_total REAL, source_file TEXT, imported_at TEXT
            );
            CREATE TABLE import_runs (
                source_file TEXT, imported_at TEXT, rows_seen INTEGER,
                rows_added INTEGER, duplicates_skipped INTEGER, invalid_rows INTEGER,
                notes TEXT
            );
            """
        )
        records = [
            {
                "submissionid": "sub-1",
                "submittedat": "2026-11-13T10:00:00Z",
                "name": "Devotee",
                "location": "Sarjapur",
                "date": "2026-11-13",
                "bookcategory": "Big Book",
                "booksubcategory": "Small books",
                "bookname": "Title",
                "language": "Kannada",
                "quantity": "2",
                "price": "60",
                "amount": "120",
                "points": "3",
                "pointstotal": "6",
            }
        ]

        try:
            with (
                patch.object(integrations, "connect", return_value=connection),
                patch.object(integrations, "get_settings", return_value={"fallback_points": "1"}),
                patch.object(
                    integrations,
                    "get_book_pricing_catalogue",
                    return_value={"title": (2.0, 50.0)},
                ),
                patch.object(
                    integrations,
                    "get_book_variant_pricing_catalogue",
                    return_value={("title", "kannada"): (3.0, 60.0)},
                ),
            ):
                first = integrations.import_distribution_responses(records)
                second = integrations.import_distribution_responses(records)
                changed_records = [dict(records[0], quantity="3", location="Updated location")]
                third = integrations.import_distribution_responses(changed_records)

            saved = connection.execute(
                "SELECT language, book_category, book_sub_category, external_submission_id, location, quantity, "
                "points, unit_price, amount_collected, reported_points_total, source_file "
                "FROM sales"
            ).fetchone()
            self.assertEqual((first["added"], first["duplicates"]), (1, 0))
            self.assertEqual((second["added"], second["duplicates"]), (0, 1))
            self.assertEqual((third["added"], third["updated"]), (0, 1))
            self.assertEqual(
                tuple(saved),
                (
                    "Kannada",
                    "Big Book",
                    "Small books",
                    "sub-1",
                    "Updated location",
                    3,
                    3.0,
                    60.0,
                    120.0,
                    6.0,
                    integrations.WEBSITE_SOURCE,
                ),
            )
        finally:
            connection.close()

    def test_submission_summary_import_is_idempotent_and_updates(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE website_submissions (
                submission_id TEXT PRIMARY KEY, submitted_at TEXT NOT NULL,
                seller_name TEXT NOT NULL, location TEXT NOT NULL,
                sale_date TEXT NOT NULL, total_copies INTEGER NOT NULL,
                total_points REAL NOT NULL, lakshmi_due REAL NOT NULL,
                lakshmi_transferred REAL NOT NULL, shastra_daan REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        record = {
            "submissionid": "sub-1",
            "submittedat": "2026-11-13T10:00:00Z",
            "name": "Devotee",
            "location": "Sarjapur",
            "date": "2026-11-13",
            "totalcopies": "3",
            "totalpoints": "4.5",
            "lakshmidue": "200",
            "lakshmitransferred": 0,
            "shastradaan": "50",
        }
        try:
            with patch.object(integrations, "connect", return_value=connection):
                first = integrations.import_distribution_submissions([record])
                unchanged = integrations.import_distribution_submissions([record])
                updated = integrations.import_distribution_submissions(
                    [dict(record, totalpoints="5")]
                )
            saved = connection.execute(
                """
                SELECT submission_id, total_copies, total_points, lakshmi_due,
                       lakshmi_transferred, shastra_daan
                FROM website_submissions
                """
            ).fetchone()
            self.assertEqual((first["added"], first["invalid"]), (1, 0))
            self.assertEqual((unchanged["added"], unchanged["unchanged"]), (0, 1))
            self.assertEqual((updated["updated"], updated["unchanged"]), (1, 0))
            self.assertEqual(tuple(saved), ("sub-1", 3, 5.0, 200.0, 0.0, 50.0))
        finally:
            connection.close()

    def test_sheet_number_preserves_numeric_zero_and_only_treats_blank_as_blank(self):
        self.assertEqual(integrations._sheet_number(0, "amount", 2), 0.0)
        self.assertEqual(
            integrations._sheet_number(0, "amount", 2, allow_blank=True),
            0.0,
        )
        self.assertIsNone(
            integrations._sheet_number(None, "amount", 2, allow_blank=True)
        )
        with self.assertRaisesRegex(ValueError, "must be a number"):
            integrations._sheet_number(None, "amount", 2)

    def test_full_sync_rolls_back_catalogue_and_responses_on_invalid_summary(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY, book_name TEXT UNIQUE COLLATE NOCASE,
                book_tag TEXT, languages TEXT, default_points REAL, price REAL,
                active INTEGER, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE book_variants (
                id INTEGER PRIMARY KEY, book_id INTEGER,
                language TEXT COLLATE NOCASE, book_category TEXT,
                book_sub_category TEXT, price REAL, points REAL, stock REAL,
                stock_value REAL, books_distributed REAL, balance_books REAL,
                amount_collected REAL, books_billed REAL, billed_amount REAL,
                books_unbilled REAL, unbilled_amount REAL, allotted_books REAL,
                allotted_books_amt REAL, ibc_s_stock REAL, ibc_s_stock_amt REAL,
                active INTEGER, updated_at TEXT,
                UNIQUE(book_id, language)
            );
            CREATE TABLE sellers (
                id INTEGER PRIMARY KEY, seller_name TEXT UNIQUE,
                active INTEGER, created_at TEXT
            );
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY, row_key TEXT UNIQUE,
                form_timestamp TEXT, seller_name TEXT, sale_date TEXT,
                book_name TEXT, language TEXT, book_category TEXT,
                book_sub_category TEXT,
                external_submission_id TEXT, location TEXT, remarks TEXT,
                points REAL, quantity INTEGER, unit_price REAL,
                amount_collected REAL, shastra_daan REAL,
                reported_points_total REAL, source_file TEXT, imported_at TEXT
            );
            CREATE TABLE import_runs (
                id INTEGER PRIMARY KEY, source_file TEXT, imported_at TEXT,
                rows_seen INTEGER, rows_added INTEGER, duplicates_skipped INTEGER,
                invalid_rows INTEGER, notes TEXT
            );
            CREATE TABLE website_submissions (
                submission_id TEXT PRIMARY KEY, submitted_at TEXT,
                seller_name TEXT, location TEXT, sale_date TEXT,
                total_copies INTEGER, total_points REAL, lakshmi_due REAL,
                lakshmi_transferred REAL, shastra_daan REAL, updated_at TEXT
            );
            CREATE TABLE lists_snapshot (
                id INTEGER PRIMARY KEY, sheet_values TEXT NOT NULL
            );
            INSERT INTO lists_snapshot VALUES (1, '[["Old"], ["previous"]]');
            """
        )
        response = {
            "submissionid": "sub-1",
            "submittedat": "2026-11-18T10:00:00Z",
            "name": "Devotee",
            "location": "Sarjapur",
            "date": "2026-11-18",
            "bookcategory": "Big Book",
            "bookname": "Title",
            "language": "English",
            "quantity": "1",
            "price": "50",
            "amount": "50",
            "points": "1",
            "pointstotal": "1",
        }
        invalid_summary = {
            "submissionid": "sub-1",
            "submittedat": "2026-11-18T10:00:00Z",
            "name": "Devotee",
            "location": "Sarjapur",
            "date": "2026-11-18",
            "totalcopies": "1",
            "totalpoints": "-1",
            "lakshmidue": "50",
            "lakshmitransferred": "50",
            "shastradaan": "0",
        }
        try:
            with (
                patch.object(integrations, "connect", return_value=connection),
                patch.object(
                    integrations,
                    "get_settings",
                    return_value={"fallback_points": "1"},
                ),
                patch.object(
                    integrations,
                    "fetch_response_sheet",
                    return_value=[response],
                ),
                patch.object(
                    integrations,
                    "fetch_submission_sheet",
                    return_value=[invalid_summary],
                ),
                patch.object(
                    integrations,
                    "_fetch_distribution_catalogue",
                    return_value=(
                        [("Title", "Big Book", "English", 50.0, 1.0)],
                        [["Book"], ["Title"]],
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "no spreadsheet data was applied",
                ):
                    integrations.sync_distribution_responses(
                        service_account_info={"type": "service_account"},
                        spreadsheet_config={
                            "spreadsheet_id": "test-sheet",
                            "lists_tab": "Lists",
                            "responses_tab": "responses",
                            "submissions_tab": "submissions",
                        },
                    )

            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM books").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM website_submissions"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                json.loads(connection.execute("SELECT sheet_values FROM lists_snapshot").fetchone()[0]),
                [["Old"], ["previous"]],
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
