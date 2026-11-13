import csv
import hashlib
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import pandas as pd
from .config import RAW_DIR, import_filename
from .db import connect
from .catalogue import (
    get_book_codes_catalogue,
    get_book_pricing_catalogue,
    sync_book_catalogue,
)
from .settings import get_settings

ALIASES = {
    "timestamp": ["Timestamp", "Submitted At", "Submission Timestamp"],
    "seller": ["Devotee", "Name", "Person", "Seller Name", "Seller", "Distributor", "Devotee Name"],
    "date": ["Date of Sale", "Sale Date", "Date", "Distribution Date"],
    "book": ["Book Sold", "Book", "Book Name", "Title"],
    "language": ["Language", "Book Language"],
    "quantity": ["Quantity", "Qty", "Number of Books", "Books Quantity"],
    "book_entries": ["Books Distributed", "Book Distribution Entries"],
    "location": ["Location", "Distribution Location"],
    "collection_total": ["Total Collection Received", "Total Laxmi Received", "Total Collection"],
    "shastra_daan_total": ["Total Shastra Daan", "Total Shastra Daan Received"],
    "books_total": ["Total Books Distributed", "Total Books"],
    "remarks": ["Remarks", "Notes"],
}

def norm(s):
    return "".join(c.lower() for c in str(s or "").strip() if c.isalnum())

def pick(row, aliases):
    normalized = {norm(k): v for k, v in row.items()}
    for alias in aliases:
        value = normalized.get(norm(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""

def parse_date(raw, dayfirst=None):
    raw = str(raw or "").strip()
    if not raw:
        return None
    ambiguous_formats = (
        ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%m/%d/%Y", "%m/%d/%y")
        if dayfirst
        else ("%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d-%m-%Y")
    )
    for fmt in (
        *ambiguous_formats,
        "%Y-%m-%d",
        "%d %b %Y",
        "%d-%b-%Y",
        "%d %B %Y",
        "%d-%B-%Y",
        "%b %d, %Y",
    ):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return pd.to_datetime(raw, errors="raise", dayfirst=bool(dayfirst)).date().isoformat()
    except Exception:
        return None


def _infer_dayfirst(dates):
    evidence = set()
    for raw in dates:
        parts = str(raw or "").strip().replace("-", "/").split("/")
        if len(parts) != 3 or len(parts[0]) == 4:
            continue
        if not parts[0].isdigit() or not parts[1].isdigit():
            continue
        first, second = int(parts[0]), int(parts[1])
        if first > 12 and second <= 12:
            evidence.add(True)
        elif second > 12 and first <= 12:
            evidence.add(False)
    return next(iter(evidence)) if len(evidence) == 1 else None


def row_key(timestamp, seller, sale_date, book, item_index=None, language=""):
    parts = [
        timestamp.strip().casefold(),
        seller.strip().casefold(),
        sale_date,
        book.strip().casefold(),
        language.strip().casefold(),
    ]
    if item_index is not None:
        parts.append(str(item_index))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def safe_raw_copy(content, archive_name):
    dest = RAW_DIR / Path(archive_name).name
    suffix = 1
    while dest.exists():
        dest = RAW_DIR / f"{Path(archive_name).stem}_{suffix}.csv"
        suffix += 1
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return dest


def _quantity_columns(rows, fieldnames):
    metadata_columns = {norm(alias) for aliases in ALIASES.values() for alias in aliases}
    columns = []
    for field in fieldnames:
        if norm(field) in metadata_columns:
            continue
        values = [str(row.get(field, "")).strip() for row in rows]
        populated_values = [value for value in values if value]
        if not populated_values:
            continue
        try:
            if all(int(value) > 0 for value in populated_values):
                columns.append(field)
        except ValueError:
            continue
    return columns


def _parse_amount(raw):
    try:
        amount = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise ValueError(f"'{raw}' is not a valid amount.") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("Amounts must be finite and non-negative.")
    return amount


def _parse_book_entries(raw, code_catalogue):
    entries = []
    errors = []
    for line_number, line in enumerate(str(raw or "").splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 4:
            errors.append(
                f"Books Distributed line {line_number} must be "
                "'BookCode | Quantity | AmountCollected | ShastraDaan'."
            )
            continue
        code, quantity_value, amount_value, daan_value = parts
        book_name = code_catalogue.get(code.casefold())
        if not book_name:
            errors.append(f"Books Distributed line {line_number}: unknown book code '{code}'.")
            continue
        try:
            quantity = int(quantity_value)
            if quantity < 1:
                raise ValueError
            amount = _parse_amount(amount_value)
            shastra_daan = _parse_amount(daan_value)
        except ValueError as exc:
            errors.append(
                f"Books Distributed line {line_number}: quantity must be a positive whole "
                f"number and amounts must be valid non-negative values ({exc})."
            )
            continue
        entries.append((book_name, quantity, float(amount), float(shastra_daan)))
    if not entries and not errors:
        errors.append("Books Distributed is empty.")
    return entries, errors


def _summary_discrepancies(row, sale_items):
    discrepancies = []
    total_collection = pick(row, ALIASES["collection_total"])
    total_daan = pick(row, ALIASES["shastra_daan_total"])
    total_books = pick(row, ALIASES["books_total"])
    if total_collection:
        try:
            reported = _parse_amount(total_collection)
            calculated = sum(
                (Decimal(str(item[2])) for item in sale_items if item[2] is not None),
                Decimal("0"),
            )
            if abs(reported - calculated) > Decimal("0.01"):
                discrepancies.append(
                    f"Total Collection Received is {reported}; book entries sum to {calculated}."
                )
        except ValueError as exc:
            discrepancies.append(f"Total Collection Received is invalid: {exc}")
    if total_daan:
        try:
            reported = _parse_amount(total_daan)
            calculated = sum(
                (Decimal(str(item[3])) for item in sale_items),
                Decimal("0"),
            )
            if abs(reported - calculated) > Decimal("0.01"):
                discrepancies.append(
                    f"Total Shastra Daan is {reported}; book entries sum to {calculated}."
                )
        except ValueError as exc:
            discrepancies.append(f"Total Shastra Daan is invalid: {exc}")
    if total_books:
        try:
            reported = int(total_books)
            calculated = sum(item[1] for item in sale_items)
            if reported != calculated:
                discrepancies.append(
                    f"Total Books Distributed is {reported}; book entries sum to {calculated}."
                )
        except ValueError:
            discrepancies.append("Total Books Distributed must be a whole number.")
    return discrepancies


def import_response_csv(content, filename):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    has_quantity_column = any(
        norm(field) in {norm(alias) for alias in ALIASES["quantity"]}
        for field in reader.fieldnames
    )
    has_book_entries = any(
        norm(field) in {norm(alias) for alias in ALIASES["book_entries"]}
        for field in reader.fieldnames
    )
    rows = list(reader)
    dayfirst = (
        True
        if has_book_entries
        else _infer_dayfirst(pick(row, ALIASES["date"]) for row in rows)
    )
    sync_book_catalogue()
    pricing_catalogue = get_book_pricing_catalogue()
    code_catalogue = get_book_codes_catalogue()
    unmatched_book_columns = [
        field
        for field in _quantity_columns(rows, reader.fieldnames)
        if field.strip().casefold() not in pricing_catalogue
    ]
    archive_name = import_filename(datetime.now().date())
    archive_path = safe_raw_copy(content, archive_name)
    settings = get_settings()
    fallback = float(settings.get("fallback_points", "1"))
    added = duplicates = invalid = 0
    issues, unknown_books = [], set()
    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")

    with connect() as con:
        for row_no, row in enumerate(rows, start=2):
            timestamp = pick(row, ALIASES["timestamp"])
            seller = pick(row, ALIASES["seller"])
            sale_date = parse_date(pick(row, ALIASES["date"]), dayfirst)
            book = pick(row, ALIASES["book"])
            location = pick(row, ALIASES["location"])
            language = pick(row, ALIASES["language"])
            remarks = pick(row, ALIASES["remarks"])
            if has_book_entries:
                sale_items, entry_errors = _parse_book_entries(
                    pick(row, ALIASES["book_entries"]), code_catalogue
                )
                if entry_errors:
                    invalid += 1
                    if len(issues) < 12:
                        issues.extend(
                            f"CSV row {row_no}: {error}"
                            for error in entry_errors[: 12 - len(issues)]
                        )
                    continue
                for discrepancy in _summary_discrepancies(row, sale_items):
                    if len(issues) < 12:
                        issues.append(f"CSV row {row_no}: {discrepancy}")
            elif book:
                quantity_value = pick(row, ALIASES["quantity"]) if has_quantity_column else "1"
                try:
                    quantity = int(quantity_value)
                except ValueError:
                    quantity = 0
                sale_items = [(book, quantity, None, 0.0)]
            else:
                sale_items = [
                    (field, str(row.get(field, "")).strip(), None, 0.0)
                    for field in reader.fieldnames
                    if field.strip().casefold() in pricing_catalogue
                    and str(row.get(field, "")).strip()
                ]
            if not seller or not sale_date or not sale_items:
                invalid += 1
                if len(issues) < 12:
                    if not sale_items and unmatched_book_columns:
                        unmatched = ", ".join(repr(name) for name in unmatched_book_columns)
                        issues.append(
                            f"CSV row {row_no}: no active catalogue titles match these "
                            f"book columns: {unmatched}. Add the titles with their price "
                            "and points in the Book catalogue, then import the CSV again."
                        )
                    else:
                        issues.append(f"CSV row {row_no}: devotee, sale date, or book/quantity is missing/invalid.")
                continue
            normalized_items = []
            invalid_quantity = None
            for item_book, quantity_value, amount_collected, shastra_daan in sale_items:
                try:
                    quantity = int(quantity_value)
                except (TypeError, ValueError):
                    quantity = 0
                if quantity < 1:
                    invalid_quantity = item_book
                    break
                normalized_items.append(
                    (item_book, quantity, amount_collected, shastra_daan)
                )
            if invalid_quantity is not None:
                invalid += 1
                if len(issues) < 12:
                    issues.append(
                        f"CSV row {row_no}: '{invalid_quantity}' quantity must be a positive whole number."
                    )
                continue
            sale_items = normalized_items
            for item_index, (book, quantity, amount_collected, shastra_daan) in enumerate(
                sale_items,
                start=1,
            ):
                con.execute(
                    "INSERT OR IGNORE INTO sellers(seller_name,active,created_at) VALUES(?,1,?)",
                    (seller, imported_at),
                )
                key = row_key(
                    timestamp,
                    seller,
                    sale_date,
                    book,
                    item_index if has_book_entries else None,
                    language,
                )
                book_pricing = pricing_catalogue.get(book.casefold())
                if book_pricing is None:
                    points = fallback
                    unit_price = 0
                    unknown_books.add(book)
                else:
                    points, unit_price = book_pricing
                cur = con.execute("""
                    INSERT OR IGNORE INTO sales
                    (row_key,form_timestamp,seller_name,sale_date,book_name,language,location,remarks,
                     points,quantity,unit_price,amount_collected,shastra_daan,source_file,imported_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    key, timestamp, seller, sale_date, book, language, location, remarks, points, quantity,
                    unit_price, amount_collected, shastra_daan, Path(filename).name, imported_at,
                ))
                if cur.rowcount:
                    added += 1
                else:
                    duplicates += 1
        con.execute("""
            INSERT INTO import_runs(source_file,imported_at,rows_seen,rows_added,duplicates_skipped,invalid_rows,notes)
            VALUES(?,?,?,?,?,?,?)
        """, (Path(filename).name, imported_at, len(rows), added, duplicates, invalid, " | ".join(issues)))

    return {
        "rows_seen": len(rows), "added": added, "duplicates": duplicates, "invalid": invalid,
        "issues": issues, "unknown_books": sorted(unknown_books),
        "unmatched_book_columns": unmatched_book_columns,
        "archive_file": archive_path.name
    }
