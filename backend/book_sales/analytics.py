from .repository import query_df
from .settings import get_settings

def dashboard_summary(sale_date=None):
    settings = get_settings()
    active_sellers = query_df("SELECT COUNT(*) AS n FROM sellers WHERE active=1").iloc[0]["n"]
    active_books = query_df("SELECT COUNT(*) AS n FROM books WHERE active=1").iloc[0]["n"]
    totals = query_df("""
        SELECT COALESCE(SUM(quantity),0) AS books_sold,
               COALESCE(SUM(COALESCE(reported_points_total, points * quantity)),0) AS points,
               COALESCE(ROUND(SUM(COALESCE(amount_collected, unit_price * quantity)),2),0) AS revenue,
               COALESCE(ROUND(SUM(shastra_daan),2),0) AS shastra_daan,
               COUNT(*) AS sale_records,
               COUNT(DISTINCT seller_name) AS participating_devotees
        FROM sales
        WHERE (? IS NULL OR sale_date = ?)
    """, (sale_date, sale_date)).iloc[0]
    return {
        "books_sold": int(totals["books_sold"]),
        "points": float(totals["points"]),
        "revenue": float(totals["revenue"]),
        "shastra_daan": float(totals["shastra_daan"]),
        "sale_records": int(totals["sale_records"]),
        "participating_devotees": int(totals["participating_devotees"]),
        "active_sellers": int(active_sellers),
        "active_books": int(active_books),
        "overall_target": float(settings.get("overall_target", "0")),
        "overall_target_start_date": settings.get("overall_target_start_date", ""),
        "overall_target_end_date": settings.get("overall_target_end_date", ""),
    }


def accumulated_points(as_of_date, start_date=None, end_date=None):
    period_end = min(as_of_date, end_date) if end_date else as_of_date
    total = query_df(
        "SELECT COALESCE(SUM(COALESCE(reported_points_total, points * quantity)), 0) AS points "
        "FROM sales WHERE sale_date <= ? "
        "AND (? IS NULL OR sale_date >= ?)",
        (period_end, start_date, start_date),
    ).iloc[0]["points"]
    return float(total)

def leaderboard(include_all_active=False, sale_date=None):
    sql = """
        SELECT s.seller_name AS seller,
               COALESCE(SUM(sa.quantity),0) AS books_sold,
               COALESCE(SUM(COALESCE(sa.reported_points_total, sa.points * sa.quantity)),0) AS points,
               COALESCE(ROUND(SUM(COALESCE(sa.amount_collected, sa.unit_price * sa.quantity)),2),0) AS revenue,
               COALESCE(ROUND(SUM(sa.shastra_daan),2),0) AS shastra_daan,
               COALESCE(t.target_points,0) AS target_points
        FROM sellers s
        LEFT JOIN sales sa ON sa.seller_name = s.seller_name COLLATE NOCASE
                         AND (? IS NULL OR sa.sale_date = ?)
        LEFT JOIN seller_targets t ON t.seller_id = s.id
    """
    if not include_all_active:
        sql += " WHERE s.active=1"
    sql += " GROUP BY s.id, s.seller_name, t.target_points ORDER BY points DESC, seller COLLATE NOCASE"
    df = query_df(sql, (sale_date, sale_date))
    if not df.empty:
        df["target_progress_pct"] = df.apply(
            lambda r: round(float(r["points"]) / float(r["target_points"]) * 100, 1) if r["target_points"] > 0 else None,
            axis=1
        )
    return df

def daily_summary(start_date=None, end_date=None):
    return query_df(
        """
        SELECT sale_date, SUM(quantity) AS books_sold,
               SUM(COALESCE(reported_points_total, points * quantity)) AS points,
               ROUND(SUM(COALESCE(amount_collected, unit_price * quantity)),2) AS revenue,
               ROUND(SUM(shastra_daan),2) AS shastra_daan
        FROM sales
        WHERE (? IS NULL OR sale_date >= ?)
          AND (? IS NULL OR sale_date <= ?)
        GROUP BY sale_date ORDER BY sale_date DESC
        """,
        (start_date, start_date, end_date, end_date),
    )


def book_performance(sale_date=None):
    return query_df(
        """
        SELECT sales.book_name AS book, sales.language AS language,
               COALESCE(books.book_tag, '') AS book_tag,
               SUM(quantity) AS copies,
               SUM(COALESCE(reported_points_total, points * quantity)) AS points,
               ROUND(SUM(COALESCE(amount_collected, unit_price * quantity)),2) AS revenue,
               ROUND(SUM(shastra_daan),2) AS shastra_daan
        FROM sales
        LEFT JOIN books ON books.book_name = sales.book_name COLLATE NOCASE
        WHERE (? IS NULL OR sale_date = ?)
        GROUP BY sales.book_name, sales.language, books.book_tag
        ORDER BY copies DESC, book COLLATE NOCASE
        """,
        (sale_date, sale_date),
    )


def list_sales():
    return query_df("""
        SELECT id, form_timestamp, external_submission_id, seller_name, sale_date,
               location, book_name, book_category, language, quantity, points,
               COALESCE(reported_points_total, points * quantity) AS total_points, unit_price,
               COALESCE(amount_collected, unit_price * quantity) AS amount_collected,
               shastra_daan, remarks, source_file, imported_at
        FROM sales ORDER BY sale_date DESC, id DESC
    """)

def list_imports():
    return query_df("""
        SELECT source_file, imported_at, rows_seen, rows_added, duplicates_skipped, invalid_rows, notes
        FROM import_runs ORDER BY id DESC LIMIT 100
    """)

def update_sale_points(sale_id, points):
    import math

    from .repository import execute
    points = float(points)
    if not math.isfinite(points) or points < 0:
        raise ValueError("Points must be a finite, non-negative number.")
    execute(
        "UPDATE sales SET points=?, reported_points_total=NULL WHERE id=?",
        (points, int(sale_id)),
    )

def export_csv(frame):
    import unicodedata

    def escape_formula(value):
        if not isinstance(value, str):
            return value
        index = 0
        while index < len(value):
            character = value[index]
            if not (
                character.isspace()
                or unicodedata.category(character) in {"Cc", "Cf"}
            ):
                break
            index += 1
        if value[index : index + 1] in ("=", "+", "-", "@"):
            return "'" + value
        return value

    return frame.map(escape_formula).to_csv(index=False).encode("utf-8-sig")


def export_sales_csv(frame):
    return export_csv(frame)
