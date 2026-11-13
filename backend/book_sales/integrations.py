import csv
import hashlib
import io
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

from .catalogue import (
    get_book_pricing_catalogue,
    get_book_variant_pricing_catalogue,
    merge_distribution_catalogue,
)
from .db import connect
from .importer import parse_date
from .repository import now_iso, query_df
from .settings import get_settings

SPREADSHEET_ID = "1dztK02kAIqPI1_L-XMpIwAWoNEH6qLQh1vp7FkeNQEQ"
CATALOGUE_CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export"
    "?format=csv&gid=2035992438"
)
RESPONSES_RANGE = "responses!A:M"
SUBMISSIONS_RANGE = "submissions!A:J"
LISTS_RANGE = "Lists!A:E"
WEBSITE_SOURCE = "IBC Sarjapur web form"
_GOOGLE_SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"


def _normalize_header(value):
    return "".join(character.lower() for character in str(value) if character.isalnum())


def parse_distribution_catalogue_csv(content):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The distribution catalogue must use UTF-8 encoding.") from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        raise ValueError("The distribution catalogue CSV has no header row.")
    columns = {_normalize_header(name): name for name in reader.fieldnames}
    required = {"bookcategory", "book", "language", "price", "points"}
    if not required.issubset(columns):
        raise ValueError(
            "The distribution catalogue must contain Book Category, Book, Language, Price, and Points columns."
        )

    rows = []
    seen = set()
    for row_number, row in enumerate(reader, start=2):
        category = str(row.get(columns["bookcategory"]) or "").strip()
        book = str(row.get(columns["book"]) or "").strip()
        language = str(row.get(columns["language"]) or "").strip()
        if not category or not book or not language:
            raise ValueError(
                f"Distribution catalogue row {row_number}: category, book, and language are required."
            )
        variant_key = (book.casefold(), language.casefold())
        if variant_key in seen:
            raise ValueError(
                f"Distribution catalogue row {row_number}: duplicate book and language."
            )
        seen.add(variant_key)
        values = []
        for field in ("price", "points"):
            raw_value = str(row.get(columns[field]) or "").strip()
            if not raw_value:
                values.append(None)
                continue
            try:
                numeric_value = float(raw_value.replace(",", ""))
            except ValueError as exc:
                raise ValueError(
                    f"Distribution catalogue row {row_number}: {field.title()} must be a number."
                ) from exc
            if not math.isfinite(numeric_value) or numeric_value < 0:
                raise ValueError(
                    f"Distribution catalogue row {row_number}: {field.title()} "
                    "must be finite and non-negative."
                )
            values.append(numeric_value)
        rows.append((book, category, language, *values))

    if not rows:
        raise ValueError("The distribution catalogue CSV contains no book rows.")
    return rows


def _catalogue_records_csv(records):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Book Category", "Book", "Language", "Price", "Points"])
    for record in records:
        writer.writerow(
            [
                record.get("bookcategory", ""),
                record.get("book", ""),
                record.get("language", ""),
                record.get("price", ""),
                record.get("points", ""),
            ]
        )
    return output.getvalue().encode("utf-8")


def sync_distribution_catalogue(api_key=None, service_account_info=None):
    if api_key or service_account_info:
        records = _fetch_sheet_records(
            LISTS_RANGE,
            {"bookcategory", "book", "language", "price", "points"},
            "Lists",
            api_key,
            service_account_info,
        )
        content = _catalogue_records_csv(records)
    else:
        request = urllib.request.Request(
            CATALOGUE_CSV_URL,
            headers={"User-Agent": "HaribolBookDistribution/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                content = response.read(2_000_001)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise ValueError(
                f"Could not download the distribution catalogue: {exc}"
            ) from exc
        if len(content) > 2_000_000:
            raise ValueError("The distribution catalogue CSV must be 2 MB or smaller.")
    return merge_distribution_catalogue(parse_distribution_catalogue_csv(content))


def _fetch_sheet_records(
    sheet_range,
    required_headers,
    sheet_label,
    api_key=None,
    service_account_info=None,
):
    api_key = str(api_key or "").strip()
    headers = {"User-Agent": "HaribolBookDistribution/1.0"}
    if service_account_info:
        try:
            from google.auth.exceptions import GoogleAuthError
            from google.auth.transport.requests import Request
            from google.oauth2.service_account import Credentials

            credentials = Credentials.from_service_account_info(
                dict(service_account_info),
                scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
            )
            credentials.refresh(Request())
            headers["Authorization"] = f"Bearer {credentials.token}"
        except (GoogleAuthError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Google service account configuration is invalid: {exc}"
            ) from exc
    elif not api_key:
        raise ValueError(
            "Add google_service_account credentials or a permitted Sheets API key "
            "to Streamlit Cloud Secrets before syncing."
        )
    encoded_range = urllib.parse.quote(sheet_range, safe="!:")
    url = f"{_GOOGLE_SHEETS_API}/{SPREADSHEET_ID}/values/{encoded_range}"
    query = {
        "valueRenderOption": "UNFORMATTED_VALUE",
        "dateTimeRenderOption": "FORMATTED_STRING",
    }
    if not service_account_info:
        query["key"] = api_key
    url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read(5_000_001).decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise ValueError(f"Could not read the {sheet_label} sheet: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"The {sheet_label} sheet returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"The {sheet_label} sheet returned an unexpected response.")
    if "error" in payload:
        error = payload["error"]
        message = (
            error.get("message", "Google Sheets API error.")
            if isinstance(error, dict)
            else str(error)
        )
        raise ValueError(f"Could not read the {sheet_label} sheet: {message}")
    values = payload.get("values")
    if not isinstance(values, list) or not values:
        return []

    headers = [_normalize_header(value) for value in values[0]]
    if not required_headers.issubset(headers):
        raise ValueError(
            f"The {sheet_label} sheet is missing required columns: "
            + ", ".join(sorted(required_headers - set(headers)))
        )

    records = []
    for row in values[1:]:
        record = {
            headers[index]: value
            for index, value in enumerate(row)
            if index < len(headers)
        }
        records.append(record)
    return records


def fetch_response_sheet(api_key=None, service_account_info=None):
    return _fetch_sheet_records(
        RESPONSES_RANGE,
        {
            "submissionid",
            "submittedat",
            "name",
            "location",
            "date",
            "bookcategory",
            "bookname",
            "language",
            "quantity",
            "price",
            "amount",
            "points",
            "pointstotal",
        },
        "responses",
        api_key,
        service_account_info,
    )


def fetch_submission_sheet(api_key=None, service_account_info=None):
    return _fetch_sheet_records(
        SUBMISSIONS_RANGE,
        {
            "submissionid",
            "submittedat",
            "name",
            "location",
            "date",
            "totalcopies",
            "totalpoints",
            "lakshmidue",
            "lakshmitransferred",
            "shastradaan",
        },
        "submissions",
        api_key,
        service_account_info,
    )


def _sheet_number(value, field, row_number, allow_blank=False):
    raw_value = str(value or "").strip()
    if not raw_value and allow_blank:
        return None
    try:
        number = Decimal(raw_value)
    except InvalidOperation as exc:
        raise ValueError(
            f"Response row {row_number}: {field} must be a number."
        ) from exc
    if not number.is_finite() or number < 0:
        raise ValueError(
            f"Response row {row_number}: {field} must be finite and non-negative."
        )
    return float(number)


def import_distribution_responses(records):
    settings = get_settings()
    try:
        fallback_points = float(settings.get("fallback_points", "1"))
    except (TypeError, ValueError) as exc:
        raise ValueError("FALLBACK_POINTS must be a valid number.") from exc
    if not math.isfinite(fallback_points) or fallback_points < 0:
        raise ValueError("FALLBACK_POINTS must be a finite, non-negative number.")

    pricing = get_book_pricing_catalogue()
    variant_pricing = get_book_variant_pricing_catalogue()
    added = updated = duplicates = invalid = 0
    issues = []
    submission_occurrences = {}
    imported_at = now_iso()

    with connect() as con:
        for row_number, record in enumerate(records, start=2):
            submission_id = str(record.get("submissionid") or "").strip()
            submitted_at = str(record.get("submittedat") or "").strip()
            seller = str(record.get("name") or "").strip()
            sale_date = parse_date(record.get("date"))
            category = str(record.get("bookcategory") or "").strip()
            book = str(record.get("bookname") or "").strip()
            language = str(record.get("language") or "").strip()
            location = str(record.get("location") or "").strip()
            try:
                quantity_value = Decimal(str(record.get("quantity") or "").strip())
                quantity = int(quantity_value)
                if not quantity_value.is_finite() or quantity_value != quantity:
                    quantity = 0
            except (InvalidOperation, ValueError, TypeError):
                quantity = 0
            try:
                sheet_price = _sheet_number(
                    record.get("price"), "price", row_number, allow_blank=True
                )
                amount_collected = _sheet_number(
                    record.get("amount"), "amount", row_number, allow_blank=True
                )
                sheet_points = _sheet_number(
                    record.get("points"), "points", row_number, allow_blank=True
                )
                reported_points_total = _sheet_number(
                    record.get("pointstotal"),
                    "points_total",
                    row_number,
                    allow_blank=True,
                )
            except ValueError as exc:
                invalid += 1
                if len(issues) < 12:
                    issues.append(str(exc))
                continue

            if (
                not submission_id
                or not seller
                or not sale_date
                or not book
                or not language
                or not category
                or quantity < 1
            ):
                invalid += 1
                if len(issues) < 12:
                    issues.append(
                        f"Response row {row_number}: submission, name, date, book, language, "
                        "category, and a positive whole-number quantity are required."
                    )
                continue

            occurrence = submission_occurrences.get(submission_id, 0) + 1
            submission_occurrences[submission_id] = occurrence
            key_source = f"{submission_id}|{occurrence}"
            row_key = hashlib.sha256(key_source.encode("utf-8")).hexdigest()
            catalogue_points, catalogue_price = variant_pricing.get(
                (book.casefold(), language.casefold()),
                pricing.get(book.casefold(), (fallback_points, 0.0)),
            )
            points = sheet_points if sheet_points is not None else catalogue_points
            unit_price = sheet_price if sheet_price is not None else catalogue_price
            con.execute(
                "INSERT OR IGNORE INTO sellers(seller_name,active,created_at) VALUES(?,1,?)",
                (seller, imported_at),
            )
            existing = con.execute(
                """
                SELECT seller_name, sale_date, book_name, language, book_category,
                   location, quantity, form_timestamp, points, unit_price,
                   amount_collected, reported_points_total
                FROM sales WHERE row_key=?
                """,
                (row_key,),
            ).fetchone()
            if existing is None:
                con.execute(
                    """
                    INSERT INTO sales
                        (row_key,form_timestamp,seller_name,sale_date,book_name,language,
                         book_category,external_submission_id,location,remarks,points,
                         quantity,unit_price,amount_collected,shastra_daan,
                         reported_points_total,source_file,imported_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)
                    """,
                    (
                        row_key,
                        submitted_at,
                        seller,
                        sale_date,
                        book,
                        language,
                        category,
                        submission_id,
                        location,
                        "",
                        points,
                        quantity,
                        unit_price,
                        amount_collected,
                        reported_points_total,
                        WEBSITE_SOURCE,
                        imported_at,
                    ),
                )
                added += 1
            else:
                source_values = (
                    submitted_at,
                    seller,
                    sale_date,
                    book,
                    language,
                    category,
                    location,
                    quantity,
                    points,
                    unit_price,
                    amount_collected,
                    reported_points_total,
                )
                existing_values = (
                    existing["form_timestamp"],
                    existing["seller_name"],
                    existing["sale_date"],
                    existing["book_name"],
                    existing["language"],
                    existing["book_category"],
                    existing["location"],
                    existing["quantity"],
                    existing["points"],
                    existing["unit_price"],
                    existing["amount_collected"],
                    existing["reported_points_total"],
                )
                if source_values != existing_values:
                    con.execute(
                        """
                        UPDATE sales
                        SET form_timestamp=?, seller_name=?, sale_date=?, book_name=?,
                            language=?, book_category=?, location=?, quantity=?,
                            points=?, unit_price=?, amount_collected=?,
                            reported_points_total=?, imported_at=?
                        WHERE row_key=?
                        """,
                        (*source_values, imported_at, row_key),
                    )
                    updated += 1
                else:
                    duplicates += 1

        if added or updated or invalid:
            notes = list(issues)
            if updated:
                notes.append(f"{updated} existing response row(s) updated.")
            con.execute(
                """
                INSERT INTO import_runs
                    (source_file,imported_at,rows_seen,rows_added,duplicates_skipped,invalid_rows,notes)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    WEBSITE_SOURCE,
                    imported_at,
                    len(records),
                    added,
                    duplicates,
                    invalid,
                    " | ".join(notes),
                ),
            )

    return {
        "rows_seen": len(records),
        "added": added,
        "updated": updated,
        "duplicates": duplicates,
        "invalid": invalid,
        "issues": issues,
    }


def import_distribution_submissions(records):
    added = updated = unchanged = invalid = 0
    issues = []
    imported_at = now_iso()
    with connect() as con:
        for row_number, record in enumerate(records, start=2):
            submission_id = str(record.get("submissionid") or "").strip()
            submitted_at = str(record.get("submittedat") or "").strip()
            seller = str(record.get("name") or "").strip()
            location = str(record.get("location") or "").strip()
            sale_date = parse_date(record.get("date"))
            try:
                total_copies_value = _sheet_number(
                    record.get("totalcopies"), "total_copies", row_number
                )
                total_copies = int(total_copies_value)
                if total_copies_value != total_copies:
                    total_copies = -1
                values = {
                    "total_points": _sheet_number(
                        record.get("totalpoints"), "total_points", row_number
                    ),
                    "lakshmi_due": _sheet_number(
                        record.get("lakshmidue"), "lakshmi_due", row_number
                    ),
                    "lakshmi_transferred": _sheet_number(
                        record.get("lakshmitransferred"),
                        "lakshmi_transferred",
                        row_number,
                    ),
                    "shastra_daan": _sheet_number(
                        record.get("shastradaan"), "shastra_daan", row_number
                    ),
                }
            except ValueError as exc:
                invalid += 1
                if len(issues) < 12:
                    issues.append(str(exc))
                continue

            if (
                not submission_id
                or not seller
                or not sale_date
                or total_copies < 0
            ):
                invalid += 1
                if len(issues) < 12:
                    issues.append(
                        f"Submission row {row_number}: submission ID, name, date, "
                        "and a non-negative whole-number total_copies are required."
                    )
                continue

            source_values = (
                submitted_at,
                seller,
                location,
                sale_date,
                total_copies,
                values["total_points"],
                values["lakshmi_due"],
                values["lakshmi_transferred"],
                values["shastra_daan"],
            )
            existing = con.execute(
                """
                SELECT submitted_at, seller_name, location, sale_date, total_copies,
                       total_points, lakshmi_due, lakshmi_transferred, shastra_daan
                FROM website_submissions WHERE submission_id=?
                """,
                (submission_id,),
            ).fetchone()
            if existing is None:
                con.execute(
                    """
                    INSERT INTO website_submissions
                        (submission_id,submitted_at,seller_name,location,sale_date,
                         total_copies,total_points,lakshmi_due,lakshmi_transferred,
                         shastra_daan,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (submission_id, *source_values, imported_at),
                )
                added += 1
            elif source_values != tuple(existing):
                con.execute(
                    """
                    UPDATE website_submissions
                    SET submitted_at=?, seller_name=?, location=?, sale_date=?,
                        total_copies=?, total_points=?, lakshmi_due=?,
                        lakshmi_transferred=?, shastra_daan=?, updated_at=?
                    WHERE submission_id=?
                    """,
                    (*source_values, imported_at, submission_id),
                )
                updated += 1
            else:
                unchanged += 1

    return {
        "rows_seen": len(records),
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "invalid": invalid,
        "issues": issues,
    }


def list_website_submissions():
    return query_df(
        """
        SELECT submission_id, submitted_at, seller_name, location, sale_date,
               total_copies, total_points, lakshmi_due, lakshmi_transferred,
               shastra_daan, updated_at
        FROM website_submissions
        ORDER BY sale_date DESC, submitted_at DESC
        """
    )


def sync_distribution_responses(api_key=None, service_account_info=None):
    records = fetch_response_sheet(api_key, service_account_info)
    submissions = fetch_submission_sheet(api_key, service_account_info)
    catalogue_result = sync_distribution_catalogue(api_key, service_account_info)
    result = import_distribution_responses(records)
    summary_result = import_distribution_submissions(submissions)
    result["catalogue_added"] = catalogue_result["added"]
    result["catalogue_updated"] = catalogue_result["updated"]
    result["variants_added"] = catalogue_result["variants_added"]
    result["variants_updated"] = catalogue_result["variants_updated"]
    result["submissions_added"] = summary_result["added"]
    result["submissions_updated"] = summary_result["updated"]
    result["submissions_unchanged"] = summary_result["unchanged"]
    result["submissions_invalid"] = summary_result["invalid"]
    result["submission_issues"] = summary_result["issues"]
    return result
