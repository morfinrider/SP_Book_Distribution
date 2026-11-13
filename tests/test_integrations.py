import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from book_sales import integrations
from book_sales import catalogue


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
                ("Title A", "Big Book", "English", 280.0, 2.0),
                ("Title A", "Big Book", "Kannada", None, 2.0),
                ("Title B", "Small Books", "Hindi", None, 0.25),
            ],
        )

    def test_catalogue_sync_reads_lists_tab_with_configured_api_key(self):
        records = [
            {
                "bookcategory": "Big Book",
                "book": "Title A",
                "language": "English",
                "price": 280,
                "points": 2,
            }
        ]
        with (
            patch.object(
                integrations,
                "_fetch_sheet_records",
                return_value=records,
            ) as fetch,
            patch.object(
                integrations,
                "merge_distribution_catalogue",
                return_value={"added": 1},
            ) as merge,
        ):
            result = integrations.sync_distribution_catalogue("test-key")

        fetch.assert_called_once_with(
            integrations.LISTS_RANGE,
            {"bookcategory", "book", "language", "price", "points"},
            "Lists",
            "test-key",
            None,
        )
        self.assertEqual(
            merge.call_args.args[0],
            [("Title A", "Big Book", "English", 280.0, 2.0)],
        )
        self.assertEqual(result, {"added": 1})

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
                book_category TEXT, price REAL, points REAL, active INTEGER,
                updated_at TEXT, UNIQUE(book_id, language)
            );
            """
        )
        rows = [
            ("Title A", "Big Book", "English", 280.0, 2.0),
            ("Title A", "Big Book", "Kannada", None, 2.0),
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
                        ("Title A", "Big Book", "English", 300.0, 3.0),
                        ("Title A", "Big Book", "Kannada", None, 2.0),
                    ]
                )
            variants = connection.execute(
                "SELECT language, price, points FROM book_variants ORDER BY language"
            ).fetchall()
            self.assertEqual(initial["variants_added"], 2)
            self.assertEqual(unchanged["variants_updated"], 0)
            self.assertEqual(updated["variants_updated"], 2)
            self.assertEqual(
                [tuple(row) for row in variants],
                [("English", 300.0, 3.0), ("Kannada", 300.0, 2.0)],
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
            rows = integrations.fetch_response_sheet("test-key")

        self.assertEqual(rows[0]["submissionid"], "sub-1")
        self.assertEqual(rows[0]["bookname"], "Title")
        self.assertIn("key=test-key", urlopen.call_args.args[0].full_url)

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
                external_submission_id TEXT, location TEXT,
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
                "SELECT language, book_category, external_submission_id, location, quantity, "
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
            "lakshmitransferred": "100",
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
            self.assertEqual(tuple(saved), ("sub-1", 3, 5.0, 200.0, 100.0, 50.0))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
