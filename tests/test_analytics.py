import csv
import io
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from book_sales.analytics import accumulated_points, export_csv, export_sales_csv
from book_sales.settings import save_settings


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            "CREATE TABLE sales (sale_date TEXT, points REAL, quantity INTEGER, "
            "reported_points_total REAL)"
        )
        self.connection.executemany(
            "INSERT INTO sales VALUES (?, ?, ?, NULL)",
            [
                ("2026-04-30", 1, 5),
                ("2026-05-01", 2, 3),
                ("2026-05-02", 4, 2),
                ("2026-05-03", 1, 10),
            ],
        )

        def query_df(sql, params):
            return pd.read_sql_query(sql, self.connection, params=params)

        self.query_patch = patch("book_sales.analytics.query_df", side_effect=query_df)
        self.query_patch.start()

    def tearDown(self):
        self.query_patch.stop()
        self.connection.close()

    def test_accumulated_points_obeys_inclusive_target_dates(self):
        self.assertEqual(
            accumulated_points("2026-05-04", "2026-05-01", "2026-05-02"),
            14,
        )
        self.assertEqual(
            accumulated_points("2026-05-01", "2026-05-02", "2026-05-03"),
            0,
        )
        self.assertEqual(accumulated_points("2026-05-02"), 19)

    def test_accumulated_points_uses_sheet_reported_total_when_present(self):
        self.connection.execute(
            "UPDATE sales SET reported_points_total=7 WHERE sale_date='2026-05-01'"
        )

        self.assertEqual(
            accumulated_points("2026-05-01", "2026-05-01", "2026-05-01"),
            7,
        )

    def test_export_escapes_formula_text_but_preserves_numbers(self):
        frame = pd.DataFrame(
            {
                "seller": [
                    "=1+1",
                    " \t@SUM(A1:A5)",
                    "\u200b-1+2",
                    "Haribol",
                ],
                "quantity": [1, 2, 3, 4],
                "amount": [10.5, 0, -2, 7],
            }
        )

        rows = list(
            csv.DictReader(
                io.StringIO(export_sales_csv(frame).decode("utf-8-sig"))
            )
        )

        self.assertEqual(
            [row["seller"] for row in rows],
            ["'=1+1", "' \t@SUM(A1:A5)", "'\u200b-1+2", "Haribol"],
        )
        self.assertEqual([row["quantity"] for row in rows], ["1", "2", "3", "4"])
        self.assertEqual([row["amount"] for row in rows], ["10.5", "0.0", "-2.0", "7.0"])

    def test_generic_csv_export_escapes_import_history_text(self):
        frame = pd.DataFrame({"notes": ["=HYPERLINK(\"bad\")"]})

        exported = export_csv(frame).decode("utf-8-sig")

        self.assertIn("'=HYPERLINK", exported)

    def test_settings_reject_a_reversed_target_period(self):
        with patch("book_sales.settings.save_env_settings") as save_env_settings:
            with self.assertRaisesRegex(ValueError, "start date"):
                save_settings(
                    {
                        "overall_target_start_date": "2026-05-03",
                        "overall_target_end_date": "2026-05-01",
                    }
                )
            save_env_settings.assert_not_called()

    def test_settings_save_configured_target_dates(self):
        with patch("book_sales.settings.save_env_settings") as save_env_settings:
            save_settings(
                {
                    "overall_target_start_date": "2026-05-01",
                    "overall_target_end_date": "2026-05-31",
                }
            )

        save_env_settings.assert_called_once_with(
            {
                "OVERALL_TARGET_START_DATE": "2026-05-01",
                "OVERALL_TARGET_END_DATE": "2026-05-31",
            }
        )


if __name__ == "__main__":
    unittest.main()
