import sqlite3
from .config import DATA_DIR, DB_PATH, RAW_DIR

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    book_tag TEXT NOT NULL DEFAULT '',
    code TEXT NOT NULL DEFAULT '',
    languages TEXT NOT NULL DEFAULT '',
    default_points REAL NOT NULL DEFAULT 1 CHECK(default_points >= 0),
    price REAL NOT NULL DEFAULT 0 CHECK(price >= 0),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS book_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    language TEXT NOT NULL COLLATE NOCASE,
    book_category TEXT NOT NULL,
    book_sub_category TEXT NOT NULL DEFAULT '',
    price REAL NOT NULL DEFAULT 0 CHECK(price >= 0),
    points REAL NOT NULL DEFAULT 1 CHECK(points >= 0),
    stock REAL CHECK(stock IS NULL OR stock >= 0),
    stock_value REAL CHECK(stock_value IS NULL OR stock_value >= 0),
    books_distributed REAL CHECK(books_distributed IS NULL OR books_distributed >= 0),
    balance_books REAL CHECK(balance_books IS NULL OR balance_books >= 0),
    amount_collected REAL CHECK(amount_collected IS NULL OR amount_collected >= 0),
    books_billed REAL CHECK(books_billed IS NULL OR books_billed >= 0),
    billed_amount REAL CHECK(billed_amount IS NULL OR billed_amount >= 0),
    books_unbilled REAL CHECK(books_unbilled IS NULL OR books_unbilled >= 0),
    unbilled_amount REAL CHECK(unbilled_amount IS NULL OR unbilled_amount >= 0),
    allotted_books REAL CHECK(allotted_books IS NULL OR allotted_books >= 0),
    allotted_books_amt REAL CHECK(allotted_books_amt IS NULL OR allotted_books_amt >= 0),
    ibc_s_stock REAL CHECK(ibc_s_stock IS NULL OR ibc_s_stock >= 0),
    ibc_s_stock_amt REAL CHECK(ibc_s_stock_amt IS NULL OR ibc_s_stock_amt >= 0),
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(book_id, language),
    FOREIGN KEY(book_id) REFERENCES books(id)
);
CREATE TABLE IF NOT EXISTS sellers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seller_targets (
    seller_id INTEGER PRIMARY KEY,
    target_points REAL NOT NULL DEFAULT 0 CHECK(target_points >= 0),
    FOREIGN KEY(seller_id) REFERENCES sellers(id)
);
CREATE TABLE IF NOT EXISTS settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lists_snapshot (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    sheet_values TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_key TEXT NOT NULL UNIQUE,
    form_timestamp TEXT NOT NULL DEFAULT '',
    seller_name TEXT NOT NULL,
    sale_date TEXT NOT NULL,
    book_name TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT '',
    book_category TEXT NOT NULL DEFAULT '',
    book_sub_category TEXT NOT NULL DEFAULT '',
    external_submission_id TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    remarks TEXT NOT NULL DEFAULT '',
    points REAL NOT NULL DEFAULT 1 CHECK(points >= 0),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    unit_price REAL NOT NULL DEFAULT 0 CHECK(unit_price >= 0),
    amount_collected REAL,
    shastra_daan REAL NOT NULL DEFAULT 0 CHECK(shastra_daan >= 0),
    reported_points_total REAL CHECK(reported_points_total >= 0),
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS website_submissions (
    submission_id TEXT PRIMARY KEY,
    submitted_at TEXT NOT NULL DEFAULT '',
    seller_name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    sale_date TEXT NOT NULL,
    total_copies INTEGER NOT NULL DEFAULT 0 CHECK(total_copies >= 0),
    total_points REAL NOT NULL DEFAULT 0 CHECK(total_points >= 0),
    lakshmi_due REAL NOT NULL DEFAULT 0 CHECK(lakshmi_due >= 0),
    lakshmi_transferred REAL NOT NULL DEFAULT 0 CHECK(lakshmi_transferred >= 0),
    shastra_daan REAL NOT NULL DEFAULT 0 CHECK(shastra_daan >= 0),
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_sales_seller ON sales(seller_name);
CREATE INDEX IF NOT EXISTS idx_sales_book ON sales(book_name);
CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    rows_seen INTEGER NOT NULL,
    rows_added INTEGER NOT NULL,
    duplicates_skipped INTEGER NOT NULL,
    invalid_rows INTEGER NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
"""

def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def normalize_seller_name(value):
    return " ".join(str(value or "").strip().split())


def seller_name_key(value):
    return normalize_seller_name(value).casefold()


def resolve_seller_name(connection, value):
    normalized = normalize_seller_name(value)
    if not normalized:
        return ""
    key = seller_name_key(normalized)
    for row in connection.execute("SELECT seller_name FROM sellers"):
        if seller_name_key(row["seller_name"]) == key:
            return normalize_seller_name(row["seller_name"])
    return normalized


def _canonicalize_seller_names(connection):
    seller_rows = connection.execute(
        "SELECT id, seller_name FROM sellers ORDER BY id"
    ).fetchall()
    groups = {}
    for row in seller_rows:
        key = seller_name_key(row["seller_name"])
        if key:
            groups.setdefault(key, []).append(row)

    for rows in groups.values():
        if len(rows) < 2:
            if rows:
                display_name = normalize_seller_name(rows[0]["seller_name"])
                connection.execute(
                    "UPDATE sellers SET seller_name=? WHERE id=?",
                    (display_name, rows[0]["id"]),
                )
                for sale in connection.execute(
                    "SELECT id, seller_name FROM sales"
                ).fetchall():
                    if seller_name_key(sale["seller_name"]) == seller_name_key(display_name):
                        connection.execute(
                            "UPDATE sales SET seller_name=? WHERE id=?",
                            (display_name, sale["id"]),
                        )
            continue

        sales_counts = {}
        for row in rows:
            sales_count = sum(
                1
                for sale in connection.execute("SELECT seller_name FROM sales")
                if seller_name_key(sale["seller_name"])
                == seller_name_key(row["seller_name"])
            )
            sales_counts[row["id"]] = sales_count
        keeper = max(rows, key=lambda row: (sales_counts[row["id"]], -row["id"]))
        display_name = normalize_seller_name(keeper["seller_name"])
        connection.execute(
            "UPDATE sellers SET seller_name=? WHERE id=?",
            (display_name, keeper["id"]),
        )

        for row in rows:
            if row["id"] != keeper["id"]:
                target = connection.execute(
                    "SELECT target_points FROM seller_targets WHERE seller_id=?",
                    (row["id"],),
                ).fetchone()
                keeper_target = connection.execute(
                    "SELECT target_points FROM seller_targets WHERE seller_id=?",
                    (keeper["id"],),
                ).fetchone()
                if target is not None and keeper_target is None:
                    connection.execute(
                        "INSERT INTO seller_targets(seller_id,target_points) VALUES(?,?)",
                        (keeper["id"], target["target_points"]),
                    )
                connection.execute(
                    "DELETE FROM seller_targets WHERE seller_id=?",
                    (row["id"],),
                )
                connection.execute(
                    "DELETE FROM sellers WHERE id=?",
                    (row["id"],),
                )

        for sale in connection.execute("SELECT id, seller_name FROM sales").fetchall():
            if seller_name_key(sale["seller_name"]) == seller_name_key(display_name):
                connection.execute(
                    "UPDATE sales SET seller_name=? WHERE id=?",
                    (display_name, sale["id"]),
                )

def initialize_database():
    from datetime import datetime
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with connect() as con:
        con.executescript(SCHEMA)
        con.execute("DROP TABLE IF EXISTS encrypted_credentials")
        _add_column_if_missing(con, "books", "price", "REAL NOT NULL DEFAULT 0 CHECK(price >= 0)")
        _add_column_if_missing(con, "books", "book_tag", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "books", "code", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "books", "languages", "TEXT NOT NULL DEFAULT ''")
        for column, definition in (
            ("book_sub_category", "TEXT NOT NULL DEFAULT ''"),
            ("stock", "REAL CHECK(stock IS NULL OR stock >= 0)"),
            ("stock_value", "REAL CHECK(stock_value IS NULL OR stock_value >= 0)"),
            ("books_distributed", "REAL CHECK(books_distributed IS NULL OR books_distributed >= 0)"),
            ("balance_books", "REAL CHECK(balance_books IS NULL OR balance_books >= 0)"),
            ("amount_collected", "REAL CHECK(amount_collected IS NULL OR amount_collected >= 0)"),
            ("books_billed", "REAL CHECK(books_billed IS NULL OR books_billed >= 0)"),
            ("billed_amount", "REAL CHECK(billed_amount IS NULL OR billed_amount >= 0)"),
            ("books_unbilled", "REAL CHECK(books_unbilled IS NULL OR books_unbilled >= 0)"),
            ("unbilled_amount", "REAL CHECK(unbilled_amount IS NULL OR unbilled_amount >= 0)"),
            ("allotted_books", "REAL CHECK(allotted_books IS NULL OR allotted_books >= 0)"),
            ("allotted_books_amt", "REAL CHECK(allotted_books_amt IS NULL OR allotted_books_amt >= 0)"),
            ("ibc_s_stock", "REAL CHECK(ibc_s_stock IS NULL OR ibc_s_stock >= 0)"),
            ("ibc_s_stock_amt", "REAL CHECK(ibc_s_stock_amt IS NULL OR ibc_s_stock_amt >= 0)"),
        ):
            _add_column_if_missing(con, "book_variants", column, definition)
        _add_column_if_missing(con, "sales", "quantity", "INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0)")
        _add_column_if_missing(con, "sales", "language", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "sales", "book_category", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "sales", "book_sub_category", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "sales", "external_submission_id", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "sales", "unit_price", "REAL NOT NULL DEFAULT 0 CHECK(unit_price >= 0)")
        _add_column_if_missing(con, "sales", "location", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "sales", "remarks", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(con, "sales", "amount_collected", "REAL")
        _add_column_if_missing(con, "sales", "shastra_daan", "REAL NOT NULL DEFAULT 0 CHECK(shastra_daan >= 0)")
        _add_column_if_missing(con, "sales", "reported_points_total", "REAL CHECK(reported_points_total >= 0)")
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_books_code "
            "ON books(code COLLATE NOCASE) WHERE code != ''"
        )
        con.execute(
            """
            INSERT OR IGNORE INTO sellers(seller_name,active,created_at)
            SELECT DISTINCT seller_name,1,? FROM sales WHERE trim(seller_name) != ''
            """,
            (now,),
        )
        _canonicalize_seller_names(con)
        con.execute("INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES ('overall_target','0')")
        con.execute("INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES ('fallback_points','1')")
        # Seed catalog and seller list only when empty, making first run demonstrable.
        count = con.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        if count == 0:
            for title, pts in [
                ("Bhagavad Gita", 1), ("Krishna Book", 1), ("Srimad Bhagavatam", 1)
            ]:
                con.execute(
                    "INSERT OR IGNORE INTO books(book_name,default_points,price,active,created_at,updated_at) VALUES(?,?,0,1,?,?)",
                    (title, pts, now, now)
                )
    from .catalogue import sync_book_catalogue
    sync_book_catalogue()

def _add_column_if_missing(con, table, column, definition):
    columns = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
