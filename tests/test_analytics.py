import csv
import io
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow.ipc
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from book_sales.analytics import (
    accumulated_points,
    export_csv,
    export_sales_csv,
    leaderboard,
)
from book_sales.settings import (
    _persistent_settings_from_secrets,
    get_settings,
    save_settings,
)


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

    def test_leaderboard_accumulates_through_today_and_shows_ten_latest_devotees(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript(
            """
            CREATE TABLE sellers (
                id INTEGER PRIMARY KEY,
                seller_name TEXT,
                active INTEGER
            );
            CREATE TABLE sales (
                seller_name TEXT,
                sale_date TEXT,
                quantity INTEGER,
                points REAL,
                reported_points_total REAL,
                amount_collected REAL,
                unit_price REAL,
                shastra_daan REAL
            );
            CREATE TABLE seller_targets (
                seller_id INTEGER,
                target_points REAL
            );
            """
        )
        connection.executemany(
            "INSERT INTO sellers VALUES (?, ?, 1)",
            [(index, f"Devotee {index:02}",) for index in range(12)],
        )
        sales = []
        for index in range(5):
            sales.append((f"Devotee {index:02}", "2026-05-03", 10, 1, None, None, 1, 0))
        for index in range(5, 8):
            sales.append((f"Devotee {index:02}", "2026-05-02", 6, 1, None, None, 1, 0))
        for index in range(8, 10):
            sales.append((f"Devotee {index:02}", "2026-05-01", 4, 1, None, None, 1, 0))
        sales.extend(
            [
                ("Devotee 00", "2026-05-02", 2, 1, None, None, 1, 0),
                ("Devotee 10", "2026-04-30", 3, 1, None, None, 1, 0),
                ("Devotee 11", "2026-05-04", 50, 1, None, None, 1, 0),
            ]
        )
        connection.executemany(
            "INSERT INTO sales VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            sales,
        )

        def query_df(sql, params):
            return pd.read_sql_query(sql, connection, params=params)

        try:
            with patch("book_sales.analytics.query_df", side_effect=query_df):
                result = leaderboard(sale_date="2026-05-03", limit=10)

            self.assertEqual(len(result), 10)
            self.assertEqual(result.iloc[0]["seller"], "Devotee 00")
            self.assertEqual(result.iloc[0]["books_sold"], 12)
            self.assertEqual(result.iloc[0]["latest_sale_date"], "2026-05-03")
            self.assertEqual(
                result["latest_sale_date"].tolist(),
                sorted(result["latest_sale_date"], reverse=True),
            )
            self.assertNotIn("Devotee 10", result["seller"].tolist())
            self.assertNotIn("Devotee 11", result["seller"].tolist())
        finally:
            connection.close()

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

    def test_google_sheet_settings_save_to_database(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)"
        )
        try:
            with patch("book_sales.settings.connect", return_value=connection):
                save_settings(
                    {
                        "spreadsheet_id": (
                            "https://docs.google.com/spreadsheets/d/"
                            "configured-sheet_id/edit"
                        ),
                        "lists_tab": "Books",
                        "responses_tab": "Web responses",
                        "submissions_tab": "Summaries",
                        "google_sheets_auto_sync": True,
                        "google_sheets_sync_interval_minutes": 5,
                        "google_sheets_manual_sync": False,
                    }
                )

            settings = dict(
                connection.execute(
                    "SELECT setting_key, setting_value FROM settings"
                ).fetchall()
            )
            self.assertEqual(settings["spreadsheet_id"], "configured-sheet_id")
            self.assertEqual(settings["lists_tab"], "Books")
            self.assertEqual(settings["google_sheets_auto_sync"], "1")
            self.assertEqual(settings["google_sheets_sync_interval_minutes"], "5")
            self.assertEqual(settings["google_sheets_manual_sync"], "0")
        finally:
            connection.close()

    def test_google_sheet_sync_settings_default_to_five_minutes_and_manual_allowed(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)"
        )
        try:
            with (
                patch("book_sales.settings.connect", return_value=connection),
                patch("book_sales.settings.get_env_setting", return_value=None),
            ):
                settings = get_settings()

            self.assertEqual(settings["google_sheets_auto_sync"], "1")
            self.assertEqual(settings["google_sheets_sync_interval_minutes"], "5")
            self.assertEqual(settings["google_sheets_manual_sync"], "1")
        finally:
            connection.close()

    def test_persistent_settings_are_normalized_and_validated(self):
        settings = _persistent_settings_from_secrets(
            {
                "app_settings": {
                    "spreadsheet_id": (
                        "https://docs.google.com/spreadsheets/d/"
                        "persistent-sheet/edit"
                    ),
                    "overall_target": 250,
                    "google_sheets_auto_sync": False,
                    "google_sheets_sync_interval_minutes": 15,
                }
            }
        )

        self.assertEqual(settings["spreadsheet_id"], "persistent-sheet")
        self.assertEqual(settings["overall_target"], "250.0")
        self.assertEqual(settings["google_sheets_auto_sync"], "0")
        self.assertEqual(settings["google_sheets_sync_interval_minutes"], "15")

    def test_persistent_settings_reject_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "sync interval"):
            _persistent_settings_from_secrets(
                {"app_settings": {"google_sheets_sync_interval_minutes": 0}}
            )
        with self.assertRaisesRegex(ValueError, "supported application settings"):
            _persistent_settings_from_secrets(
                {"app_settings": {"unknown_setting": "value"}}
            )

    def test_persistent_settings_override_database_values(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE settings (setting_key TEXT PRIMARY KEY, setting_value TEXT)"
        )
        connection.executemany(
            "INSERT INTO settings VALUES (?, ?)",
            [("overall_target", "20"), ("spreadsheet_id", "database-sheet")],
        )
        try:
            with (
                patch("book_sales.settings.connect", return_value=connection),
                patch("book_sales.settings.get_env_setting", return_value=None),
                patch(
                    "book_sales.settings.get_persistent_settings",
                    return_value={
                        "overall_target": "250.0",
                        "spreadsheet_id": "persistent-sheet",
                    },
                ),
            ):
                settings = get_settings()

            self.assertEqual(settings["overall_target"], "250.0")
            self.assertEqual(settings["spreadsheet_id"], "persistent-sheet")
        finally:
            connection.close()

    def test_google_sheet_sync_interval_must_be_whole_minutes_between_one_and_1440(self):
        for invalid_interval in (0, 1441, 5.5, "five"):
            with self.subTest(interval=invalid_interval):
                with self.assertRaisesRegex(ValueError, "sync interval"):
                    save_settings(
                        {
                            "google_sheets_sync_interval_minutes": invalid_interval,
                        }
                    )

    def test_google_sheet_sync_boolean_settings_reject_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            save_settings({"google_sheets_manual_sync": "sometimes"})


class DashboardChartTests(unittest.TestCase):
    def test_dashboard_charts_are_labeled_static_bars(self):
        summary = {
            "books_sold": 3, "points": 2, "revenue": 150, "shastra_daan": 10,
            "sale_records": 1, "participating_devotees": 1, "overall_target": 0,
            "overall_target_start_date": "", "overall_target_end_date": "",
        }
        daily = pd.DataFrame([
            {"sale_date": "2026-11-23", "books_sold": 3, "revenue": 150, "shastra_daan": 10}
        ])
        multiple_days = pd.concat([
            daily,
            pd.DataFrame([
                {"sale_date": "2026-11-20", "books_sold": 5, "revenue": 200, "shastra_daan": 0}
            ]),
        ], ignore_index=True)
        books = pd.DataFrame([
            {"book": "Book A", "language": "English", "book_tag": "", "copies": 3,
             "points": 2, "revenue": 150, "shastra_daan": 10}
        ])
        image = (Path(__file__).resolve().parents[1] / "assets" / "Srila_Prabhupada.jpeg").read_bytes()
        with (
            patch("book_sales.db.initialize_database"),
            patch("book_sales.services.get_settings", return_value={"google_sheets_auto_sync": "0"}),
            patch("book_sales.services.dashboard_summary", return_value=summary),
            patch("book_sales.services.leaderboard", return_value=pd.DataFrame()),
            patch("book_sales.services.accumulated_points", return_value=0),
            patch("book_sales.services.daily_summary", return_value=daily) as daily_summary,
            patch("book_sales.services.book_performance", return_value=books),
            patch(
                "book_sales.services.distribution_report",
                return_value={"period_start_date": "", "period_end_date": ""},
            ),
            patch("book_sales.report_image.render_distribution_report_jpeg", return_value=image),
        ):
            app = AppTest.from_file(
                str(Path(__file__).resolve().parents[1] / "streamlit_app.py")
            ).run()
            daily_summary.return_value = multiple_days
            multiple_days_app = AppTest.from_file(
                str(Path(__file__).resolve().parents[1] / "streamlit_app.py")
            ).run()

        self.assertFalse(app.exception)
        headings = [element.value for element in app.markdown]
        for heading in (
            "#### Copies distributed by date",
            "#### Collection received by date",
            "#### Shastra Daan by date",
            "#### Top books by copies distributed",
        ):
            self.assertIn(heading, headings)
        charts = app.get("vega_lite_chart")
        self.assertEqual(len(charts), 4)
        for chart, field, title in zip(
            charts[:3],
            ("books_sold", "revenue", "shastra_daan"),
            ("Copies distributed", "Collection received (₹)", "Shastra Daan (₹)"),
        ):
            spec = json.loads(chart.proto.spec)
            self.assertNotIn("params", spec)
            self.assertEqual(spec["mark"]["type"], "bar")
            self.assertEqual(spec["encoding"]["x"]["title"], "Date")
            self.assertEqual(spec["encoding"]["x"]["timeUnit"], "yearmonthdate")
            self.assertEqual(spec["encoding"]["y"]["field"], field)
            self.assertEqual(spec["encoding"]["y"]["title"], title)
            data = pyarrow.ipc.open_stream(chart.proto.datasets[0].data.data).read_all().to_pandas()
            self.assertEqual(data.iloc[0][field], daily.iloc[0][field])
        self.assertFalse(multiple_days_app.exception)
        multi_chart = multiple_days_app.get("vega_lite_chart")[0]
        data = pyarrow.ipc.open_stream(multi_chart.proto.datasets[0].data.data).read_all().to_pandas()
        self.assertEqual(data["sale_date"].tolist(), ["2026-11-20", "2026-11-23"])
        self.assertEqual(data["books_sold"].tolist(), [5, 3])
        bar_spec = json.loads(charts[3].proto.spec)
        self.assertNotIn("params", bar_spec)
        self.assertEqual(bar_spec["layer"][0]["encoding"]["y"]["title"], "Book (language)")
        data = pyarrow.ipc.open_stream(charts[3].proto.datasets[0].data.data).read_all().to_pandas()
        self.assertEqual(data.iloc[0]["Book and language"], "Book A (English)")
        self.assertEqual(data.iloc[0]["Copies distributed"], 3)


if __name__ == "__main__":
    unittest.main()
