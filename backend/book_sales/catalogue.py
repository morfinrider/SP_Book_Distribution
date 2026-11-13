import csv
import math
from typing import Optional

from .config import BOOK_CATALOGUE_PATH
from .repository import execute, query_df, now_iso
from .db import connect

def _write_catalogue_file():
    books = list_books(include_inactive=False)
    BOOK_CATALOGUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = BOOK_CATALOGUE_PATH.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8-sig", newline="") as catalogue_file:
        writer = csv.writer(catalogue_file)
        writer.writerow(["book_name", "code", "book_tag", "price", "points"])
        for _, book in books.iterrows():
            writer.writerow([
                book["book_name"],
                book["code"],
                book["book_tag"],
                f'{float(book["price"]):.2f}',
                str(float(book["default_points"])),
            ])
    temporary_path.replace(BOOK_CATALOGUE_PATH)

def sync_book_catalogue():
    if not BOOK_CATALOGUE_PATH.exists():
        _write_catalogue_file()

    with BOOK_CATALOGUE_PATH.open(encoding="utf-8-sig", newline="") as catalogue_file:
        rows = _parse_catalogue(catalogue_file)

    _apply_catalogue_rows(rows)


def _parse_catalogue(source):
    reader = csv.DictReader(source)
    required_columns = {"book_name", "price", "points"}
    if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
        raise ValueError("Book catalogue CSV must contain book_name, price, and points columns.")
    has_code = "code" in reader.fieldnames
    has_tag = "book_tag" in reader.fieldnames
    rows = []
    seen_names = set()
    seen_codes = set()
    for row_number, row in enumerate(reader, start=2):
        name = (row.get("book_name") or "").strip()
        if not name:
            raise ValueError(f"Book catalogue row {row_number}: book_name is required.")
        if name.casefold() in seen_names:
            raise ValueError(f"Book catalogue row {row_number}: duplicate book title '{name}'.")
        seen_names.add(name.casefold())
        try:
            price = float(row["price"])
            points = float(row["points"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Book catalogue row {row_number}: price and points must be valid numbers.") from exc
        if not math.isfinite(price) or not math.isfinite(points) or price < 0 or points < 0:
            raise ValueError(f"Book catalogue row {row_number}: price and points cannot be negative.")
        code = (row.get("code") or "").strip() if has_code else None
        book_tag = (row.get("book_tag") or "").strip() if has_tag else None
        if code:
            if code.casefold() in seen_codes:
                raise ValueError(f"Book catalogue row {row_number}: duplicate book code '{code}'.")
            seen_codes.add(code.casefold())
        rows.append((name, price, points, code, book_tag))
    return rows


def merge_distribution_catalogue(rows):
    now = now_iso()
    added = updated = 0
    variants_added = variants_updated = 0
    active_variant_keys = set()
    grouped = {}
    for name, category, language, price, points in rows:
        key = name.casefold()
        entry = grouped.setdefault(
            key, {"name": name, "categories": set(), "variants": []}
        )
        entry["categories"].add(category)
        entry["variants"].append((language, price, points))

    with connect() as con:
        for entry in grouped.values():
            name = entry["name"]
            category = " / ".join(
                sorted(entry["categories"], key=str.casefold)
            )
            languages = sorted(
                {language for language, _, _ in entry["variants"]},
                key=str.casefold,
            )
            existing = con.execute(
                "SELECT id, book_tag, languages, price, default_points, active "
                "FROM books WHERE book_name=? COLLATE NOCASE",
                (name,),
            ).fetchone()
            is_new_book = existing is None
            existing_variants = {}
            if existing is not None:
                existing_variants = {
                    row["language"].casefold(): row
                    for row in con.execute(
                        "SELECT language, book_category, price, points, active "
                        "FROM book_variants "
                        "WHERE book_id=?",
                        (existing["id"],),
                    )
                }
            configured_prices = [
                price for _, price, _ in entry["variants"] if price is not None
            ]
            title_price = configured_prices[0] if configured_prices else None
            title_points = next(
                (
                    points
                    for language, _, points in entry["variants"]
                    if language.casefold() == "english" and points is not None
                ),
                next(
                    (points for _, _, points in entry["variants"] if points is not None),
                    None,
                ),
            )
            if existing is None:
                con.execute(
                    """
                    INSERT INTO books
                        (book_name, book_tag, languages, default_points, price, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        name,
                        category,
                        ", ".join(languages),
                        title_points if title_points is not None else 1,
                        title_price if title_price is not None else 0,
                        now,
                        now,
                    ),
                )
                added += 1
                existing = con.execute(
                    "SELECT id, book_tag, languages, price, default_points, active "
                    "FROM books WHERE book_name=? COLLATE NOCASE",
                    (name,),
                ).fetchone()
            language_text = ", ".join(languages)
            new_base_price = (
                title_price if title_price is not None else float(existing["price"])
            )
            new_base_points = (
                title_points
                if title_points is not None
                else float(existing["default_points"])
            )
            if (
                existing["book_tag"] != category
                or existing["languages"] != language_text
                or float(existing["price"]) != new_base_price
                or float(existing["default_points"]) != new_base_points
                or not existing["active"]
            ):
                con.execute(
                    """
                    UPDATE books SET book_tag=?, languages=?, price=?, default_points=?,
                        active=1, updated_at=? WHERE id=?
                    """,
                    (
                        category,
                        language_text,
                        new_base_price,
                        new_base_points,
                        now,
                        existing["id"],
                    ),
                )
                if not is_new_book:
                    updated += 1

            for language, source_price, source_points in entry["variants"]:
                previous = existing_variants.get(language.casefold())
                variant_price = (
                    source_price
                    if source_price is not None
                    else title_price
                    if title_price is not None
                    else float(previous["price"])
                    if previous is not None
                    else new_base_price
                )
                variant_points = (
                    source_points
                    if source_points is not None
                    else float(previous["points"])
                    if previous is not None
                    else new_base_points
                )
                if previous is None:
                    con.execute(
                        """
                        INSERT INTO book_variants
                            (book_id,language,book_category,price,points,active,updated_at)
                        VALUES(?,?,?,?,?,1,?)
                        """,
                        (
                            existing["id"],
                            language,
                            category,
                            variant_price,
                            variant_points,
                            now,
                        ),
                    )
                    variants_added += 1
                else:
                    if (
                        previous["price"] != variant_price
                        or previous["points"] != variant_points
                        or previous["language"] != language
                        or previous["book_category"] != category
                        or not previous["active"]
                    ):
                        con.execute(
                            """
                            UPDATE book_variants
                            SET language=?, book_category=?, price=?, points=?,
                                active=1, updated_at=?
                            WHERE book_id=? AND language=? COLLATE NOCASE
                            """,
                            (
                                language,
                                category,
                                variant_price,
                                variant_points,
                                now,
                                existing["id"],
                                previous["language"],
                            ),
                        )
                        variants_updated += 1
                active_variant_keys.add((name.casefold(), language.casefold()))

        for variant in con.execute(
            """
            SELECT v.id, b.book_name, v.language
            FROM book_variants v JOIN books b ON b.id=v.book_id
            WHERE v.active=1
            """
        ).fetchall():
            if (
                variant["book_name"].casefold(),
                variant["language"].casefold(),
            ) not in active_variant_keys:
                con.execute(
                    "UPDATE book_variants SET active=0, updated_at=? WHERE id=?",
                    (now, variant["id"]),
                )
    _write_catalogue_file()
    return {
        "added": added,
        "updated": updated,
        "variants_added": variants_added,
        "variants_updated": variants_updated,
    }


def list_book_variants(include_inactive=False):
    sql = """
        SELECT v.id, b.book_name, v.book_category, v.language, v.price, v.points,
               v.active, v.updated_at
        FROM book_variants v
        JOIN books b ON b.id = v.book_id
    """
    if not include_inactive:
        sql += " WHERE v.active=1"
    sql += " ORDER BY b.book_name COLLATE NOCASE, v.language COLLATE NOCASE"
    return query_df(sql)


def get_book_variant_pricing_catalogue():
    variants = list_book_variants()
    return {
        (str(row["book_name"]).casefold(), str(row["language"]).casefold()): (
            float(row["points"]),
            float(row["price"]),
        )
        for _, row in variants.iterrows()
    }


def _apply_catalogue_rows(rows):
    now = now_iso()
    with connect() as con:
        configured_names = {name.casefold() for name, _, _, _, _ in rows}
        for name, price, points, code, book_tag in rows:
            con.execute(
                """
                INSERT INTO books(book_name, code, book_tag, default_points, price, active, created_at, updated_at)
                VALUES(?,?, ?,?,?,1,?,?)
                ON CONFLICT(book_name) DO UPDATE SET
                    code=CASE WHEN ? IS NULL THEN books.code ELSE ? END,
                    book_tag=CASE WHEN ? IS NULL THEN books.book_tag ELSE ? END,
                    default_points=excluded.default_points, price=excluded.price,
                    active=1, updated_at=excluded.updated_at
                WHERE books.default_points != excluded.default_points
                   OR books.price != excluded.price OR books.active != 1
                   OR (? IS NOT NULL AND books.code != ?)
                   OR (? IS NOT NULL AND books.book_tag != ?)
                """,
                (
                    name, code or "", book_tag or "", points, price, now, now,
                    code, code or "", book_tag, book_tag or "",
                    code, code or "", book_tag, book_tag or "",
                ),
            )
        for book in con.execute("SELECT id, book_name FROM books WHERE active=1").fetchall():
            if book["book_name"].casefold() not in configured_names:
                con.execute("UPDATE books SET active=0, updated_at=? WHERE id=?", (now, book["id"]))


def add_book(
    name: str,
    points: float = 1.0,
    price: float = 0.0,
    book_tag: str = "",
    code: str = "",
) -> None:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Book title is required.")
    price, points = float(price), float(points)
    book_tag = str(book_tag or "").strip()
    code = str(code or "").strip()
    if not math.isfinite(price) or price < 0:
        raise ValueError("Price cannot be negative.")
    if not math.isfinite(points) or points < 0:
        raise ValueError("Points must be a finite, non-negative number.")
    now = now_iso()
    try:
        execute(
            "INSERT INTO books(book_name,book_tag,code,default_points,price,active,created_at,updated_at) "
            "VALUES(?,?,?,?,?,1,?,?)",
            (name, book_tag, code, points, price, now, now),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            message = (
                "A book with that short code already exists."
                if "IDX_BOOKS_CODE" in str(exc).upper()
                else "A book with that title already exists."
            )
            raise ValueError(message) from exc
        raise
    _write_catalogue_file()

def update_book(
    book_id: int,
    points: float,
    price: Optional[float] = None,
    name: Optional[str] = None,
    active: Optional[bool] = None,
    book_tag: Optional[str] = None,
    code: Optional[str] = None,
) -> None:
    points = float(points)
    if not math.isfinite(points) or points < 0:
        raise ValueError("Points must be a finite, non-negative number.")
    updates = ["default_points=?"]
    values = [points]
    if price is not None:
        price = float(price)
        if not math.isfinite(price) or price < 0:
            raise ValueError("Price cannot be negative.")
        updates.append("price=?")
        values.append(price)
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ValueError("Book title is required.")
        updates.append("book_name=?")
        values.append(name)
    if active is not None:
        updates.append("active=?")
        values.append(int(bool(active)))
    if book_tag is not None:
        updates.append("book_tag=?")
        values.append(str(book_tag or "").strip())
    if code is not None:
        updates.append("code=?")
        values.append(str(code or "").strip())
    updates.append("updated_at=?")
    values.extend([now_iso(), int(book_id)])
    try:
        execute(
            f"UPDATE books SET {', '.join(updates)} WHERE id=?",
            tuple(values),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            message = (
                "A book with that short code already exists."
                if "IDX_BOOKS_CODE" in str(exc).upper()
                else "A book with that title already exists."
            )
            raise ValueError(message) from exc
        raise
    _write_catalogue_file()

def deactivate_book(book_id):
    execute("UPDATE books SET active=0, updated_at=? WHERE id=?", (now_iso(), int(book_id)))
    _write_catalogue_file()

def list_books(include_inactive=False):
    sql = "SELECT id, book_name, book_tag, code, languages, price, default_points, active, created_at, updated_at FROM books"
    if not include_inactive:
        sql += " WHERE active=1"
    sql += " ORDER BY book_name COLLATE NOCASE"
    return query_df(sql)

def get_book_pricing(name):
    df = query_df("SELECT default_points, price FROM books WHERE book_name = ? COLLATE NOCASE AND active=1", (name,))
    if df.empty:
        return None
    return float(df.iloc[0]["default_points"]), float(df.iloc[0]["price"])

def get_book_pricing_catalogue():
    books = list_books()
    return {
        str(book["book_name"]).casefold(): (float(book["default_points"]), float(book["price"]))
        for _, book in books.iterrows()
    }


def get_book_codes_catalogue():
    books = list_books()
    return {
        str(book["code"]).strip().casefold(): str(book["book_name"])
        for _, book in books.iterrows()
        if str(book["code"]).strip()
    }


def refresh_sales_prices_from_catalogue():
    with connect() as con:
        cursor = con.execute(
            """
            UPDATE sales
            SET unit_price = (
                SELECT price FROM books
                WHERE books.book_name = sales.book_name COLLATE NOCASE
            )
            WHERE unit_price != (
                SELECT price FROM books
                WHERE books.book_name = sales.book_name COLLATE NOCASE
            )
            AND amount_collected IS NULL
            AND source_file != 'IBC Sarjapur web form'
            AND EXISTS (
                SELECT 1 FROM books
                WHERE books.book_name = sales.book_name COLLATE NOCASE
            )
            """
        )
        return cursor.rowcount
