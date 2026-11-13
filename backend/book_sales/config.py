import os
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]


def _read_app_version():
    changelog_path = PROJECT_DIR / "CHANGELOG.md"
    if not changelog_path.exists():
        raise FileNotFoundError(f"Release history is missing: {changelog_path}")
    match = re.search(
        r"^## \[(\d+\.\d+\.\d+)\]",
        changelog_path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"No semantic version found in {changelog_path}")
    return match.group(1)


def _read_env_file():
    values = {}
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        return values
    with env_path.open(encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values

def _setting(name, default):
    return get_env_setting(name, default)


def get_env_setting(name, default=None):
    if name in os.environ:
        return os.environ[name]
    return _read_env_file().get(name, default)

APP_NAME = _setting("APP_NAME", "Haribol_Book_Distribution")
APP_VERSION = _read_app_version()
IMPORT_FILENAME_PATTERN = _setting("IMPORT_FILENAME_PATTERN", "book_sales_{date}.csv")
_DATA_DIR_SETTING = Path(
    _setting("BOOK_SALES_DATA_DIR", "Haribol_Book_Distribution_Data")
).expanduser()
DATA_DIR = (
    _DATA_DIR_SETTING
    if _DATA_DIR_SETTING.is_absolute()
    else PROJECT_DIR / _DATA_DIR_SETTING
).resolve()
DB_PATH = DATA_DIR / "book_sales.sqlite3"
RAW_DIR = DATA_DIR / "raw"
BOOK_CATALOGUE_PATH = DATA_DIR / "book_catalogue.csv"
ENV_FILE = PROJECT_DIR / ".env"

def import_filename(for_date, pattern=None):
    if pattern is None:
        pattern = get_env_setting(
            "IMPORT_FILENAME_PATTERN", "book_sales_{date}.csv"
        )
    try:
        filename = pattern.format(date=for_date.isoformat())
    except (KeyError, ValueError) as exc:
        raise ValueError("IMPORT_FILENAME_PATTERN must use {date} for the ISO date.") from exc
    if not filename.lower().endswith(".csv") or Path(filename).name != filename:
        raise ValueError("IMPORT_FILENAME_PATTERN must produce a simple .csv filename.")
    return filename


def save_env_settings(values):
    allowed_keys = {
        "APP_NAME",
        "BOOK_SALES_DATA_DIR",
        "IMPORT_FILENAME_PATTERN",
        "OVERALL_POINTS_TARGET",
        "OVERALL_TARGET_START_DATE",
        "OVERALL_TARGET_END_DATE",
        "FALLBACK_POINTS",
    }
    if any(key not in allowed_keys for key in values):
        raise ValueError("Only supported application settings can be saved.")

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    updated_keys = set()
    updated_lines = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in values:
            updated_lines.append(f"{key}={values[key]}")
            updated_keys.add(key)
        else:
            updated_lines.append(line)
    for key, value in values.items():
        if key not in updated_keys:
            updated_lines.append(f"{key}={value}")

    temporary_file = ENV_FILE.with_suffix(".env.tmp")
    temporary_file.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    temporary_file.replace(ENV_FILE)
