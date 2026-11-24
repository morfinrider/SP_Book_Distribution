"""Start or stop the Haribol_Book_Distribution dashboard."""
import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import time
import shutil
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
from book_sales.config import (
    DATA_DIR,
)

APP = Path(__file__).resolve()
STATE_FILE = DATA_DIR / "Haribol_Book_Distribution.state.json"
LOG_FILE = DATA_DIR / "Haribol_Book_Distribution.log"
STARTUP_TIMEOUT_SECONDS = 90


def _load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read app state at {STATE_FILE}: {exc}") from exc


def _send_control(state, action):
    with socket.create_connection(
        (state["host"], int(state["port"])), timeout=3
    ) as connection:
        connection.sendall(f"{action}:{state['token']}\n".encode("utf-8"))
        response = connection.recv(256).decode("utf-8").strip()
    return response


def _app_is_healthy(port):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/_stcore/health", timeout=0.5
        ) as response:
            return response.status == 200 and response.read() == b"ok"
    except (OSError, urllib.error.URLError):
        return False


def _wait_for_app(port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _app_is_healthy(port):
            return True
        time.sleep(0.2)
    return _app_is_healthy(port)


def _runtime_environment():
    env = os.environ.copy()
    env["BOOK_SALES_DATA_DIR"] = str(DATA_DIR)
    backend_path = str(ROOT / "backend")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        backend_path + os.pathsep + existing_pythonpath
        if existing_pythonpath
        else backend_path
    )
    return env


def _migrate_legacy_data():
    legacy_data = ROOT / "data"
    if (
        not os.environ.get("BOOK_SALES_DATA_DIR")
        and DATA_DIR != legacy_data
        and not DATA_DIR.exists()
        and legacy_data.exists()
    ):
        shutil.move(str(legacy_data), str(DATA_DIR))


def start():
    if importlib.util.find_spec("streamlit") is None:
        raise RuntimeError(
            "Dependencies are not installed. Run: "
            "python -m pip install -r requirements.txt"
        )

    _migrate_legacy_data()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        state = _load_state()
        try:
            response = _send_control(state, "status")
        except ConnectionRefusedError:
            STATE_FILE.unlink()
        else:
            if response != "running":
                raise RuntimeError(
                    "An app control service is listening, but did not identify "
                    "this application. The state file was left unchanged."
                )
            existing_port = int(
                state.get("web_port", os.environ.get("BOOK_SALES_PORT", "8501"))
            )
            if _wait_for_app(existing_port, 5):
                print("Haribol_Book_Distribution is already running.")
                print(f"Open http://127.0.0.1:{existing_port}")
                return

            try:
                response = _send_control(state, "stop")
            except ConnectionRefusedError:
                response = "stopped"
                if STATE_FILE.exists():
                    current_state = _load_state()
                    if current_state.get("token") == state.get("token"):
                        STATE_FILE.unlink()
            if response not in ("stopping", "stopped"):
                raise RuntimeError(
                    "The stale app control service did not confirm the stop request."
                )
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and STATE_FILE.exists():
                time.sleep(0.1)
            if STATE_FILE.exists():
                raise RuntimeError(
                    f"The unresponsive app instance could not be stopped. "
                    f"Check the log: {LOG_FILE}"
                )

    token = secrets.token_urlsafe(32)
    env = _runtime_environment()
    env["HBD_CONTROL_TOKEN"] = token
    with LOG_FILE.open("ab") as log_file:
        options = {
            "cwd": ROOT,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        supervisor = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_serve"],
            **options,
        )

    port = int(env.get("BOOK_SALES_PORT", "8501"))
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if supervisor.poll() is not None:
            raise RuntimeError(
                f"App startup failed. Check the log: {LOG_FILE}"
            )
        if STATE_FILE.exists():
            state = _load_state()
            if state.get("token") == token:
                if _app_is_healthy(port):
                    print("Haribol_Book_Distribution started.")
                    print(f"Open http://127.0.0.1:{port}")
                    print(f"To stop it: python {Path(__file__).name} stop")
                    print(f"Application log: {LOG_FILE}")
                    return
        time.sleep(0.1)

    if STATE_FILE.exists():
        state = _load_state()
        if state.get("token") == token:
            try:
                _send_control(state, "stop")
            except ConnectionRefusedError:
                STATE_FILE.unlink(missing_ok=True)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and STATE_FILE.exists():
                time.sleep(0.1)
    supervisor.terminate()
    raise RuntimeError(f"App startup timed out. Check the log: {LOG_FILE}")


def stop():
    if not STATE_FILE.exists():
        print("Haribol_Book_Distribution is not running.")
        return

    state = _load_state()
    try:
        response = _send_control(state, "stop")
    except ConnectionRefusedError:
        STATE_FILE.unlink()
        print("Haribol_Book_Distribution was not running; removed stale state.")
        return
    if response != "stopping":
        raise RuntimeError(
            "The app control service did not confirm the stop request."
        )

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and STATE_FILE.exists():
        time.sleep(0.1)
    if STATE_FILE.exists():
        raise RuntimeError(
            f"The app did not stop in time. Check the log: {LOG_FILE}"
        )
    print("Haribol_Book_Distribution stopped.")


def _serve():
    token = os.environ["HBD_CONTROL_TOKEN"]
    stop_requested = False

    class ControlHandler(socketserver.BaseRequestHandler):
        def handle(self):
            nonlocal stop_requested
            message = self.request.recv(256).decode("utf-8").strip()
            try:
                action, supplied_token = message.split(":", 1)
            except ValueError:
                self.request.sendall(b"invalid\n")
                return
            if not hmac.compare_digest(supplied_token, token):
                self.request.sendall(b"unauthorized\n")
                return
            if action == "status":
                self.request.sendall(b"running\n")
            elif action == "stop":
                stop_requested = True
                self.request.sendall(b"stopping\n")
            else:
                self.request.sendall(b"invalid\n")

    class ControlServer(socketserver.TCPServer):
        allow_reuse_address = True

    with ControlServer(("127.0.0.1", 0), ControlHandler) as server:
        server.timeout = 0.25
        env = _runtime_environment()
        env["HBD_STREAMLIT_RUN"] = "1"
        state = {
            "host": "127.0.0.1",
            "port": server.server_address[1],
            "token": token,
            "web_port": int(env.get("BOOK_SALES_PORT", "8501")),
        }
        command = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(APP),
            "--server.address",
            "127.0.0.1",
            "--server.port",
            env.get("BOOK_SALES_PORT", "8501"),
            "--browser.gatherUsageStats",
            "false",
            "--server.headless",
            "true",
        ]
        with LOG_FILE.open("ab") as log_file:
            app_process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

        temporary_state = STATE_FILE.with_suffix(".tmp")
        temporary_state.write_text(json.dumps(state), encoding="utf-8")
        temporary_state.replace(STATE_FILE)
        try:
            while app_process.poll() is None and not stop_requested:
                server.handle_request()
        finally:
            if app_process.poll() is None:
                app_process.terminate()
                try:
                    app_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    app_process.kill()
                    app_process.wait()
            if STATE_FILE.exists():
                current_state = _load_state()
                if current_state.get("token") == token:
                    STATE_FILE.unlink()



def _render_app():

    from datetime import date, datetime, timedelta

    import sqlite3
    import threading
    import altair as alt
    import streamlit as st

    from book_sales.config import (
        APP_NAME,
        APP_VERSION,
    )
    from book_sales.db import initialize_database
    from book_sales.services import (
        add_seller,
        book_performance,
        catalogue_inventory_snapshot,
        dashboard_summary,
        accumulated_points,
        create_backup_zip,
        export_sales_csv,
        get_persistent_settings,
        get_settings,
        get_lists_snapshot,
        leaderboard,
        list_imports,
        list_sales,
        list_book_variants,
        list_seller_targets,
        list_sellers,
        list_website_submissions,
        daily_summary,
        export_csv,
        save_settings,
        set_seller_target,
        summarize_inventory_values,
        sync_distribution_catalogue,
        sync_distribution_responses,
        test_google_sheets_connection,
        load_google_service_account,
        update_sale_points,
        unmatched_website_response_totals,
        distribution_report,
    )
    from book_sales.report_image import render_distribution_report_jpeg

    st.set_page_config(page_title=APP_NAME, page_icon="📖", layout="wide")
    initialize_database()
    for key in st.session_state.pop("_clear_settings_inputs", []):
        st.session_state.pop(key, None)

    st.markdown(
        """
        <style>
        :root {
            --green-950: #123b2b;
            --green-900: #174c36;
            --green-800: #216447;
            --green-700: #2c805a;
            --green-100: #e8f3ec;
            --green-50: #f4f8f4;
            --ink: #1d3026;
            --muted: #718077;
        }
        html, body {
            font-family: "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
        }
        .stApp {
            background: linear-gradient(145deg, #f5f8f4 0%, #f8faf7 55%, #eff5ef 100%);
            color: var(--ink);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #123b2b 0%, #184a35 100%);
            border-right: 1px solid rgba(255,255,255,.08);
        }
        [data-testid="stSidebar"] * { color: #f4f8f4; }
        [data-testid="stSidebar"] [data-testid="stExpander"] {
            border: 1px solid rgba(255,255,255,.14);
            border-radius: 12px;
            background: rgba(255,255,255,.055);
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] summary {
            background: transparent !important;
            color: #f4f8f4 !important;
        }
        [data-testid="stSidebar"] [data-testid="stExpander"] summary * {
            color: #f4f8f4 !important;
        }
        [data-testid="stSidebar"] [data-testid="stButton"] button {
            border: 0;
            border-radius: 9px;
            background: transparent;
            text-align: left;
            font-weight: 600;
        }
        [data-testid="stSidebar"] [data-testid="stButton"] button:hover {
            background: rgba(255,255,255,.13);
            border-color: transparent;
        }
        .brand-mark {
            font-size: 2.7rem;
            line-height: 1;
            margin: .25rem 0 .7rem;
        }
        .brand-name {
            font-family: Georgia, "Palatino Linotype", serif;
            font-size: 1.2rem;
            line-height: 1.25;
            font-weight: 700;
            letter-spacing: .01em;
        }
        .brand-caption {
            color: #c5dece;
            font-size: .8rem;
            margin-top: .45rem;
            margin-bottom: 1.25rem;
        }
        .page-eyebrow {
            text-transform: uppercase;
            color: var(--green-700);
            letter-spacing: .12em;
            font-size: .72rem;
            font-weight: 750;
            margin-bottom: .25rem;
            overflow-wrap: anywhere;
        }
        .page-title {
            display: block;
            width: 100%;
            max-width: none;
            color: var(--green-950);
            font-family: Georgia, "Palatino Linotype", serif;
            font-size: clamp(2.1rem, 3.5vw, 2.8rem);
            font-weight: 700;
            letter-spacing: -.025em;
            line-height: 1.15;
            margin: 0 0 .45rem;
            overflow-wrap: anywhere;
            white-space: normal;
        }
        .page-subtitle {
            display: block;
            width: 100%;
            color: var(--green-800);
            max-width: none;
            font-size: 1rem;
            line-height: 1.65;
            background: linear-gradient(105deg, rgba(232,243,236,.95), rgba(255,255,255,.8));
            border-left: 3px solid var(--green-700);
            border-radius: 0 12px 12px 0;
            padding: .75rem 1rem;
            margin: 0 0 1.5rem;
            overflow-wrap: anywhere;
            white-space: normal;
        }
        h2, h3 { color: var(--green-900) !important; }
        [data-testid="stMetric"] {
            background: linear-gradient(155deg, #ffffff 0%, #f8fbf8 100%);
            border: 1px solid #dce8de;
            border-top: 3px solid #65a17d;
            border-radius: 14px;
            padding: .95rem 1.05rem;
            box-shadow: 0 7px 22px rgba(23,76,54,.065);
            min-height: 7.25rem;
            transition: box-shadow .18s ease, transform .18s ease;
        }
        [data-testid="stMetric"]:hover {
            box-shadow: 0 10px 26px rgba(23,76,54,.11);
            transform: translateY(-2px);
        }
        [data-testid="stMetricLabel"] {
            color: var(--muted);
            font-weight: 600;
        }
        [data-testid="stMetricValue"] {
            color: var(--green-900);
            font-family: Georgia, "Palatino Linotype", serif;
        }
        [data-testid="stMetricDelta"] { font-size: .78rem; }
        [data-testid="stDataFrame"], [data-testid="stTable"] {
            border: 1px solid #e1eae2;
            border-radius: 12px;
            overflow: hidden;
            background: white;
        }
        [data-testid^="stBaseButton-primary"] {
            background: var(--green-800);
            border-color: var(--green-800);
            color: white;
            border-radius: 9px;
            font-weight: 650;
        }
        [data-testid^="stBaseButton-primary"]:hover {
            background: var(--green-900);
            border-color: var(--green-900);
        }
        [data-testid="stExpander"] {
            border: 1px solid #e1eae2;
            border-radius: 12px;
            background: rgba(255,255,255,.8);
        }
        [data-testid="stDataFrame"] {
            box-shadow: 0 6px 18px rgba(23,76,54,.04);
        }
        [data-testid="stPlotlyChart"], [data-testid="stVegaLiteChart"] {
            border: 1px solid #e1eae2;
            border-radius: 14px;
            padding: .35rem;
            background: white;
        }
        [data-testid="stMainBlockContainer"] {
            box-sizing: border-box;
            width: 100%;
            max-width: 100%;
            padding-left: clamp(1rem, 3vw, 3rem);
            padding-right: clamp(1rem, 3vw, 3rem);
            padding-top: 4rem;
            padding-bottom: 3rem;
        }
        @media (prefers-reduced-motion: reduce) {
            [data-testid="stMetric"] { transition: none; }
            [data-testid="stMetric"]:hover { transform: none; }
        }
        .welcome-note {
            color: var(--green-800);
            background: var(--green-100);
            border-left: 4px solid var(--green-700);
            border-radius: 0 10px 10px 0;
            padding: .8rem 1rem;
            margin: .5rem 0 1.2rem;
            font-family: Georgia, "Palatino Linotype", serif;
            box-shadow: 0 5px 16px rgba(23,76,54,.06);
        }
        .mantra-note {
            text-align: center;
            line-height: 1.8;
            font-size: 1.08rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    PAGES = {
        "Overview": ("⌂", "Dashboard"),
        "Refresh dashboard": ("↻", "Dashboard"),
        "Sales records": ("▤", "Dashboard"),
        "Response entry": ("↗", "Dashboard"),
        "Book catalogue": ("▣", "Manage"),
        "Devotees & targets": ("♙", "Manage"),
        "Settings": ("⚙", "Manage"),
    }


    def _google_sheet_config():
        settings = get_settings()
        return {
            key: str(settings.get(key, "")).strip()
            for key in (
                "spreadsheet_id",
                "lists_tab",
                "responses_tab",
                "submissions_tab",
            )
        }


    def _google_sheet_credentials():
        return load_google_service_account(st.secrets)

    def _google_sync_setting_enabled(settings, key):
        return str(settings.get(key, "1")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @st.cache_resource
    def _google_sync_runtime():
        return {
            "lock": threading.Lock(),
            "last_attempt_monotonic": None,
            "last_success_at": None,
            "last_config_fingerprint": None,
            "last_error": None,
            "waiting_for_credentials": False,
            "last_warning": None,
        }

    def _run_google_sync(
        sync_action,
        record_full_sync=False,
        config_fingerprint=None,
    ):
        runtime = _google_sync_runtime()
        if not runtime["lock"].acquire(blocking=False):
            raise ValueError(
                "Another Google Sheets sync is already running. Try again when it finishes."
            )
        try:
            result = sync_action()
            if record_full_sync:
                _record_full_sync_success(
                    result,
                    config_fingerprint=config_fingerprint,
                )
            return result
        finally:
            runtime["lock"].release()

    def _record_full_sync_success(result, config_fingerprint=None):
        runtime = _google_sync_runtime()
        runtime["last_attempt_monotonic"] = time.monotonic()
        runtime["last_success_at"] = datetime.now().astimezone().strftime(
            "%Y-%m-%d %H:%M:%S %Z"
        )
        runtime["last_config_fingerprint"] = (
            config_fingerprint
            if config_fingerprint is not None
            else _google_sheet_config_fingerprint(_google_sheet_config())
        )
        runtime["last_error"] = None
        runtime["waiting_for_credentials"] = False
        runtime["last_warning"] = result.get("catalogue_file_warning")

    def _render_google_sheets_auto_sync():
        sync_settings = get_settings()
        auto_sync_enabled = _google_sync_setting_enabled(
            sync_settings, "google_sheets_auto_sync"
        )
        interval_minutes = int(
            sync_settings.get("google_sheets_sync_interval_minutes", "5")
        )

        @st.fragment(
            run_every=interval_minutes * 60 if auto_sync_enabled else None
        )
        def _auto_sync_fragment():
            current_settings = get_settings()
            if not _google_sync_setting_enabled(
                current_settings, "google_sheets_auto_sync"
            ):
                st.caption(
                    "Automatic Google Sheets sync is disabled. Change this in "
                    "Settings → Google Sheets sync schedule."
                )
                return

            current_interval = int(
                current_settings.get("google_sheets_sync_interval_minutes", "5")
            )
            spreadsheet_config = _google_sheet_config()
            config_fingerprint = _google_sheet_config_fingerprint(
                spreadsheet_config
            )
            runtime = _google_sync_runtime()
            if not spreadsheet_config["spreadsheet_id"]:
                runtime["last_attempt_monotonic"] = time.monotonic()
                runtime["last_config_fingerprint"] = config_fingerprint
                runtime["last_error"] = None
                runtime["waiting_for_credentials"] = False
                st.caption(
                    "Automatic sync is enabled. Configure a spreadsheet ID and tab "
                    "names in Settings → Google Sheets connection to begin."
                )
                return
            now = time.monotonic()
            last_attempt = runtime["last_attempt_monotonic"]
            due = (
                last_attempt is None
                or runtime["last_config_fingerprint"] != config_fingerprint
                or runtime["waiting_for_credentials"]
                or now - last_attempt >= current_interval * 60
            )
            if due and runtime["lock"].acquire(blocking=False):
                try:
                    now = time.monotonic()
                    last_attempt = runtime["last_attempt_monotonic"]
                    due = (
                        last_attempt is None
                        or runtime["last_config_fingerprint"] != config_fingerprint
                        or runtime["waiting_for_credentials"]
                        or now - last_attempt >= current_interval * 60
                    )
                    if due:
                        runtime["last_attempt_monotonic"] = now
                        runtime["last_config_fingerprint"] = config_fingerprint
                        runtime["last_error"] = None
                        runtime["waiting_for_credentials"] = False
                        try:
                            service_account_info = _google_sheet_credentials()
                            if not service_account_info:
                                runtime["waiting_for_credentials"] = True
                            else:
                                result = sync_distribution_responses(
                                    service_account_info=service_account_info,
                                    spreadsheet_config=spreadsheet_config,
                                )
                                _record_full_sync_success(
                                    result,
                                    config_fingerprint=config_fingerprint,
                                )
                                st.rerun(scope="app")
                        except (ValueError, OSError, sqlite3.Error) as exc:
                            runtime["last_error"] = str(exc)
                finally:
                    runtime["lock"].release()

            runtime = _google_sync_runtime()
            if runtime["last_error"]:
                st.error(
                    "Automatic Google Sheets sync failed. The app will retry after "
                    f"{current_interval} minutes: {runtime['last_error']}"
                )
            elif runtime["waiting_for_credentials"]:
                st.caption(
                    "Automatic sync is enabled, but is waiting for "
                    "[google_service_account] in Streamlit Secrets."
                )
            elif runtime["last_warning"]:
                st.warning(
                    f"Google Sheets data synced; catalogue file warning: "
                    f"{runtime['last_warning']}"
                )
            elif runtime["last_success_at"]:
                st.caption(
                    f"All configured Google Sheets tabs last synced at "
                    f"{runtime['last_success_at']}. Automatic sync runs every "
                    f"{current_interval} minutes while a dashboard session is open."
                )
            else:
                st.caption(
                    "Automatic sync will run immediately when credentials are "
                    "and a spreadsheet are configured, then every "
                    f"{current_interval} minutes while a "
                    "dashboard session is open."
                )

        _auto_sync_fragment()


    def _google_sheet_config_fingerprint(config):
        serialized = json.dumps(config, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


    def _secure_action_feedback(
        message,
        is_error=False,
        is_warning=False,
        clear_keys=None,
    ):
        st.session_state["_secure_action_feedback"] = {
            "message": str(message),
            "is_error": bool(is_error),
            "is_warning": bool(is_warning),
        }
        if clear_keys:
            st.session_state["_clear_settings_inputs"] = clear_keys
        st.rerun()


    def _render_secure_action_feedback():
        feedback = st.session_state.pop("_secure_action_feedback", None)
        if not feedback:
            return
        if feedback["is_error"]:
            st.error(feedback["message"])
        elif feedback["is_warning"]:
            st.warning(feedback["message"])
        else:
            st.success(feedback["message"])


    def _sidebar_navigation():
        if "active_page" not in st.session_state:
            st.session_state.active_page = "Overview"
        elif st.session_state.active_page == "Import CSV":
            st.session_state.active_page = "Overview"
        elif st.session_state.active_page == "Website entries":
            st.session_state.active_page = "Response entry"
        elif st.session_state.active_page == "Sellers & targets":
            st.session_state.active_page = "Devotees & targets"

        with st.sidebar:
            st.markdown('<div class="brand-mark">📖</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="brand-name">{APP_NAME.replace("_", " ")}</div>'
                '<div class="brand-caption">A thoughtful way to track every book shared.</div>',
                unsafe_allow_html=True,
            )
            for group in ("Dashboard", "Manage"):
                pages = [name for name, (_, category) in PAGES.items() if category == group]
                with st.expander(group, expanded=True):
                    for name in pages:
                        icon = PAGES[name][0]
                        label = f"{icon}  {name}"
                        if st.button(
                            label,
                            key=f"navigate_{name}",
                            use_container_width=True,
                            type="primary" if st.session_state.active_page == name else "secondary",
                        ):
                            st.session_state.active_page = (
                                "Overview" if name == "Refresh dashboard" else name
                            )
                            st.rerun()
            st.divider()
            st.caption(f"PUBLIC DASHBOARD  ·  v{APP_VERSION}")
            return st.session_state.active_page


    def _page_heading(eyebrow, title, subtitle):
        st.markdown(
            f'<div class="page-eyebrow">{eyebrow}</div>'
            f'<div class="page-title">{title}</div>'
            f'<div class="page-subtitle">{subtitle}</div>',
            unsafe_allow_html=True,
        )


    def _leaderboard_labels(frame):
        return frame.rename(
            columns={
                "seller": "Devotee",
                "books_sold": "Copies distributed",
                "points": "Points earned",
                "revenue": "Collection received (₹)",
                "shastra_daan": "Shastra Daan (₹)",
                "latest_sale_date": "Latest distribution",
                "target_points": "Points target",
                "target_progress_pct": "Target progress (%)",
            }
        )


    def _sales_display_frame(frame):
        return frame.rename(
            columns={
                "form_timestamp": "Submitted at",
                "external_submission_id": "Submission ID",
                "seller_name": "Devotee",
                "sale_date": "Sale date",
                "location": "Location",
                "book_name": "Book",
                "book_category": "Book category",
                "book_sub_category": "Book subcategory",
                "language": "Language",
                "quantity": "Copies",
                "points": "Points per copy",
                "total_points": "Total points",
                "unit_price": "Price per copy",
                "amount_collected": "Amount collected (₹)",
                "shastra_daan": "Shastra Daan (₹)",
                "remarks": "Remarks",
                "source_file": "Source file",
                "imported_at": "Imported at",
            }
        )


    def _render_overview():
        _page_heading(
            "Your impact at a glance",
            "Book distribution",
            "Actually producing and distributing books is our most important engagement, "
            "all other engagements culminate in this one end — distribution of books. "
            "(Letter to: Tamala Krsna  —  Bhaktivedanta Manor 27 July, 1973)",
        )
        photo_path = ROOT / "assets" / "Srila_Prabhupada.jpeg"
        if photo_path.is_file():
            photo_column, mantra_column = st.columns([1, 2], vertical_alignment="center")
            with photo_column:
                st.image(str(photo_path), caption="Srila Prabhupada", use_container_width=True)
            with mantra_column:
                st.markdown(
                    '<div class="welcome-note mantra-note">'
                    "Hare Krishna Hare Krishna,<br>"
                    "Krishna Krishna Hare Hare,<br>"
                    "Hare Rama, Hare Rama,<br>"
                    "Rama Rama, Hare Hare"
                    "</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="welcome-note mantra-note">'
                "Hare Krishna Hare Krishna,<br>"
                "Krishna Krishna Hare Hare,<br>"
                "Hare Rama, Hare Rama,<br>"
                "Rama Rama, Hare Hare"
                "</div>",
                unsafe_allow_html=True,
            )
        selected_date = st.date_input(
            "Analytics date", value=date.today(), key="overview_date"
        )
        summary = dashboard_summary(selected_date.isoformat())
        previous_summary = dashboard_summary(
            (selected_date - timedelta(days=1)).isoformat()
        )
        leaders = leaderboard(sale_date=date.today().isoformat(), limit=10)
        average_copies_per_record = (
            summary["books_sold"] / summary["sale_records"]
            if summary["sale_records"]
            else 0
        )
        metrics = (
            (
                "Copies distributed",
                f"{summary['books_sold']:,}",
                f"{summary['books_sold'] - previous_summary['books_sold']:+,} vs prior day",
            ),
            (
                "Points earned",
                f"{summary['points']:,.2f}",
                f"{summary['points'] - previous_summary['points']:+,.2f} vs prior day",
            ),
            (
                "Collection received",
                f"₹{summary['revenue']:,.2f}",
                f"₹{summary['revenue'] - previous_summary['revenue']:+,.2f} vs prior day",
            ),
            (
                "Shastra Daan",
                f"₹{summary['shastra_daan']:,.2f}",
                f"₹{summary['shastra_daan'] - previous_summary['shastra_daan']:+,.2f} vs prior day",
            ),
            (
                "Devotees participating",
                f"{summary['participating_devotees']:,}",
                None,
            ),
            ("Avg. copies per sale", f"{average_copies_per_record:,.1f}", None),
        )
        for column, (label, value, delta) in zip(st.columns(len(metrics)), metrics):
            column.metric(label, value, delta=delta)

        target = summary["overall_target"]
        target_start_date = summary["overall_target_start_date"] or None
        target_end_date = summary["overall_target_end_date"] or None
        accumulated = accumulated_points(
            selected_date.isoformat(),
            start_date=target_start_date,
            end_date=target_end_date,
        )
        percentage = min(100.0, accumulated / target * 100) if target > 0 else 0
        with st.expander("Overall target progress", expanded=True):
            if target_start_date or target_end_date:
                st.caption(
                    "Target period: "
                    f"{target_start_date or 'all time'} to {target_end_date or 'selected date'}"
                )
            if target > 0:
                st.progress(int(percentage), text=f"{accumulated:,.2f} / {target:,.2f} points  ·  {percentage:.1f}%")
            else:
                st.info("Set an overall points target in Settings to track progress.")

        st.caption(
            f"Daily figures for {selected_date.isoformat()}. Collection and Shastra Daan "
            "use the amounts reported on each book entry; legacy imports use catalogue prices."
        )

        with st.expander("Distribution trend", expanded=True):
            trend_period = st.selectbox(
                "Trend period",
                ("Last 7 days", "Last 30 days", "Last 90 days", "All time"),
                index=1,
                key="overview_trend_period",
            )
            period_days = {
                "Last 7 days": 7,
                "Last 30 days": 30,
                "Last 90 days": 90,
            }.get(trend_period)
            trend_start = (
                (selected_date - timedelta(days=period_days - 1)).isoformat()
                if period_days is not None
                else None
            )
            daily = daily_summary(trend_start, selected_date.isoformat())
            if daily.empty:
                st.info("Daily totals will appear after importing sales.")
            else:
                trend = daily.sort_values("sale_date").set_index("sale_date")
                active_days = len(trend)
                total_copies = int(trend["books_sold"].sum())
                best_day = trend["books_sold"].idxmax()
                best_day_copies = int(trend["books_sold"].max())
                average_daily_copies = total_copies / active_days
                trend_metrics = st.columns(2)
                trend_metrics[0].metric(
                    "Avg. copies per active day", f"{average_daily_copies:,.1f}"
                )
                trend_metrics[1].metric(
                    "Best day",
                    f"{best_day_copies:,} copies",
                    str(best_day),
                )
                st.caption("Each bar represents a day with recorded sales.")
                for title, field, axis_label, color in (
                    ("Copies distributed by date", "books_sold", "Copies distributed", "#2C805A"),
                    ("Collection received by date", "revenue", "Collection received (₹)", "#D39A3F"),
                    ("Shastra Daan by date", "shastra_daan", "Shastra Daan (₹)", "#7084B5"),
                ):
                    st.markdown(f"#### {title}")
                    chart = (
                        alt.Chart(trend.reset_index())
                        .mark_bar(color=color)
                        .encode(
                            x=alt.X(
                                "sale_date:T",
                                timeUnit="yearmonthdate",
                                title="Date",
                                axis=alt.Axis(format="%d %b %Y", labelAngle=-35),
                            ),
                            y=alt.Y(f"{field}:Q", title=axis_label),
                        )
                        .properties(height=240)
                    )
                    st.altair_chart(chart, use_container_width=True)

        with st.expander("Top 10 most active devotees", expanded=True):
            if leaders.empty:
                st.info("Import response data to see the leaderboard.")
            else:
                st.dataframe(
                    _leaderboard_labels(leaders),
                    use_container_width=True,
                    hide_index=True,
                )

        with st.expander("Daily reports", expanded=False):
            report = distribution_report(selected_date.isoformat())
            report_jpeg = render_distribution_report_jpeg(report)
            report_period_end = report["period_end_date"] or selected_date.isoformat()
            st.image(
                report_jpeg,
                caption="Daily and overall distribution summary through the selected date.",
                use_container_width=True,
            )
            st.caption(
                "Report period: "
                f"{report['period_start_date'] or 'all time'} through {report_period_end}. "
                "Daily totals are shown only when the selected date falls inside this period."
            )
            st.download_button(
                "Download report as JPEG",
                data=report_jpeg,
                file_name=f"book_distribution_report_{selected_date.isoformat()}.jpg",
                mime="image/jpeg",
            )

        with st.expander("Book performance for selected date", expanded=True):
            books = book_performance(selected_date.isoformat())
            if books.empty:
                st.info("Book performance will appear when sales are recorded for this date.")
            else:
                books = books.rename(
                    columns={
                        "book": "Book",
                        "language": "Language",
                        "book_tag": "Book tag",
                        "copies": "Copies distributed",
                        "points": "Points earned",
                        "revenue": "Collection received (₹)",
                        "shastra_daan": "Shastra Daan (₹)",
                    }
                )
                st.dataframe(
                    books.head(8),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Points earned": st.column_config.NumberColumn(format="%.2f"),
                        "Collection received (₹)": st.column_config.NumberColumn(format="%.2f"),
                        "Shastra Daan (₹)": st.column_config.NumberColumn(format="%.2f"),
                    },
                )
                st.markdown("#### Top books by copies distributed")
                chart_books = books.head(8).copy()
                languages = chart_books["Language"].fillna("").astype(str).str.strip()
                chart_books["Book and language"] = chart_books["Book"].astype(str).where(
                    languages.eq(""),
                    chart_books["Book"].astype(str) + " (" + languages + ")",
                )
                chart = alt.Chart(chart_books).encode(
                    x=alt.X(
                        "Copies distributed:Q",
                        title="Copies distributed",
                        scale=alt.Scale(
                            domainMin=0,
                            domainMax=max(1, float(chart_books["Copies distributed"].max()) * 1.15),
                        ),
                    ),
                    y=alt.Y(
                        "Book and language:N",
                        title="Book (language)",
                        sort="-x",
                        axis=alt.Axis(labelLimit=320),
                    ),
                )
                st.altair_chart(
                    (chart.mark_bar(color="#2C805A") + chart.mark_text(
                        align="left", dx=5
                    ).encode(text=alt.Text("Copies distributed:Q", format=",.0f")))
                    .properties(height=max(220, len(chart_books) * 40)),
                    use_container_width=True,
                )


    def _render_sales():
        _page_heading("Records", "Sales history", "Find, review, and export imported sales.")
        sales = list_sales()
        if sales.empty:
            st.info("No sales records have been imported yet.")
            return

        with st.expander("Filter sales", expanded=True):
            first, second, third = st.columns(3)
            devotee_names = ["All devotees"] + sorted(sales["seller_name"].dropna().unique().tolist())
            devotee_filter = first.selectbox("Devotee", devotee_names)
            date_filter = second.text_input("Sale date", placeholder="YYYY-MM-DD")
            book_filter = third.text_input("Book title contains", placeholder="Search titles")
        view = sales.copy()
        if devotee_filter != "All devotees":
            view = view[view["seller_name"] == devotee_filter]
        if date_filter.strip():
            view = view[view["sale_date"] == date_filter.strip()]
        if book_filter.strip():
            view = view[view["book_name"].str.contains(book_filter.strip(), case=False, na=False)]
        st.caption(
            f"{len(view)} matching sale record(s). Historical sale prices remain unchanged "
            "until refreshed from the current catalogue."
        )
        display_view = _sales_display_frame(view)
        st.dataframe(display_view, use_container_width=True, hide_index=True)
        st.download_button(
            "Download filtered CSV",
            export_sales_csv(display_view),
            "book_sales_export.csv",
            "text/csv",
        )

        with st.expander("Adjust points for a historical sale"):
            st.warning("This changes points for this sale only; it does not update the catalogue.")
            ids = view["id"].tolist()
            if ids:
                selected_id = st.selectbox("Sale record ID", ids)
                selected_row = view[view["id"] == selected_id].iloc[0]
                new_points = st.number_input(
                    "Points per book",
                    min_value=0.0,
                    max_value=100000.0,
                    value=float(selected_row["points"]),
                    step=0.01,
                    format="%.2f",
                )
                if st.button("Save historical points", type="primary"):
                    update_sale_points(int(selected_id), float(new_points))
                    st.success("Historical sale updated.")
                    st.rerun()


    def _render_website_entries():
        _page_heading(
            "IBC Sarjapur · Book Marathon 2026",
            "Response entry",
            "Use the existing public entry form and sync its response sheet into this dashboard.",
        )
        entry_tab, responses_tab = st.tabs(["Enter distribution", "Synced responses"])
        with entry_tab:
            st.warning(
                "This form is public at books.iskw.in, even when this dashboard is private. "
                "Anyone with the form URL can submit there."
            )
            st.iframe(
                "https://books.iskw.in/",
                height=1050,
            )
        with responses_tab:
            st.caption(
                "Credentials are read from Streamlit Secrets. Remote rows are fetched and "
                "validated before any local changes are committed."
            )
            _render_secure_action_feedback()
            sync_settings = get_settings()
            if not _google_sync_setting_enabled(
                sync_settings, "google_sheets_manual_sync"
            ):
                st.caption(
                    "Manual sync is disabled. Enable it in Settings → Google Sheets "
                    "sync schedule."
                )
            else:
                try:
                    service_account_info = _google_sheet_credentials()
                except ValueError as exc:
                    service_account_info = None
                    st.error(f"Invalid Google service-account secret: {exc}")
                if not service_account_info:
                    st.info(
                        "Configure [google_service_account] in Streamlit Secrets before syncing."
                    )
                else:
                    with st.form("website_response_sync_form"):
                        sync_requested = st.form_submit_button(
                            "Sync website responses now",
                            type="primary",
                        )
                    if sync_requested:
                        try:
                            spreadsheet_config = _google_sheet_config()
                            config_fingerprint = _google_sheet_config_fingerprint(
                                spreadsheet_config
                            )
                            result = _run_google_sync(
                                lambda: sync_distribution_responses(
                                    service_account_info=service_account_info,
                                    spreadsheet_config=spreadsheet_config,
                                ),
                                record_full_sync=True,
                                config_fingerprint=config_fingerprint,
                            )
                            st.session_state.website_responses_last_sync = (
                                time.monotonic()
                            )
                            _secure_action_feedback(
                                f"Sync complete: {result['added']} added, "
                                f"{result['updated']} updated, "
                                f"{result['duplicates']} unchanged. Catalogue: "
                                f"{result['catalogue_added']} new title(s), "
                                f"{result['catalogue_updated']} updated; summaries: "
                                f"{result['submissions_added']} new, "
                                f"{result['submissions_updated']} updated."
                                + (
                                    f" {result['catalogue_file_warning']}"
                                    if result.get("catalogue_file_warning")
                                    else ""
                                ),
                                is_warning=bool(result.get("catalogue_file_warning")),
                            )
                        except (ValueError, OSError, sqlite3.Error) as exc:
                            _secure_action_feedback(
                                f"Could not sync website responses: {exc}",
                                is_error=True,
                            )

            last_sync = st.session_state.get("website_responses_last_sync")
            if last_sync is not None:
                st.caption("Last successful sync completed in this session.")

            book_rows_tab, submissions_tab = st.tabs(
                ["Book-level responses", "Submission summaries"]
            )
            with book_rows_tab:
                website_sales = list_sales()
                website_sales = website_sales[
                    website_sales["source_file"] == "IBC Sarjapur web form"
                ]
                if website_sales.empty:
                    st.info("No website responses have been synced yet.")
                else:
                    sales_display = _sales_display_frame(website_sales)
                    st.caption(
                        f"{len(website_sales):,} website response row(s) are in the app's sales history."
                    )
                    st.dataframe(
                        sales_display,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.download_button(
                        "Download website responses CSV",
                        export_sales_csv(sales_display),
                        "ibc_sarjapur_book_distribution.csv",
                        "text/csv",
                    )
            with submissions_tab:
                summaries = list_website_submissions()
                if summaries.empty:
                    st.info("No submission summaries have been synced yet.")
                else:
                    summaries = summaries.rename(
                        columns={
                            "submission_id": "Submission ID",
                            "submitted_at": "Submitted at",
                            "seller_name": "Name",
                            "location": "Location",
                            "sale_date": "Date",
                            "total_copies": "Total copies",
                            "total_points": "Total points",
                            "lakshmi_due": "Lakshmi due",
                            "lakshmi_transferred": "Lakshmi transferred",
                            "shastra_daan": "Shastra Daan",
                        }
                    ).drop(columns=["updated_at"])
                    st.dataframe(
                        summaries,
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.download_button(
                        "Download submission summaries CSV",
                        export_csv(summaries),
                        "ibc_sarjapur_submission_summaries.csv",
                        "text/csv",
                    )



    def _render_catalogue():
        _page_heading(
            "Books & values",
            "Book catalogue",
            "Browse book categories, prices, points, and inventory synced from the spreadsheet.",
        )
        st.caption(
            "The Google Sheet is the source of truth. Update its Lists tab to change the "
            "catalogue and inventory; this page is read-only. The full workbook sync runs "
            "automatically on the configured schedule. Manual refresh uses the Google "
            "service account configured in Streamlit Secrets."
        )
        _render_secure_action_feedback()
        sync_settings = get_settings()
        if not _google_sync_setting_enabled(sync_settings, "google_sheets_manual_sync"):
            st.caption(
                "Manual sync is disabled. Enable it in Settings → Google Sheets "
                "sync schedule."
            )
        else:
            try:
                service_account_info = _google_sheet_credentials()
            except ValueError as exc:
                service_account_info = None
                st.error(f"Invalid Google service-account secret: {exc}")
            if service_account_info:
                with st.form("catalogue_sync_form"):
                    sync_requested = st.form_submit_button(
                        "Sync book list from Google Sheet",
                        type="primary",
                    )
                if sync_requested:
                    try:
                        result = _run_google_sync(
                            lambda: sync_distribution_catalogue(
                                service_account_info=service_account_info,
                                spreadsheet_config=_google_sheet_config(),
                            )
                        )
                        st.session_state.book_catalogue_last_sync = time.monotonic()
                        _secure_action_feedback(
                            f"Catalogue sync complete: {result['added']} new title(s), "
                            f"{result['updated']} title(s) updated; "
                            f"{result['variants_added']} new language variant(s), "
                            f"{result['variants_updated']} updated."
                            + (
                                f" {result['catalogue_file_warning']}"
                                if result.get("catalogue_file_warning")
                                else ""
                            ),
                            is_warning=bool(result.get("catalogue_file_warning")),
                        )
                    except (ValueError, OSError, sqlite3.Error) as exc:
                        _secure_action_feedback(
                            f"Could not sync the book list: {exc}",
                            is_error=True,
                        )
            else:
                st.info(
                    "Configure [google_service_account] in Streamlit Secrets before syncing."
                )

        snapshot = get_lists_snapshot()
        if snapshot is None:
            st.markdown("#### Lists sheet")
            st.info("Sync the spreadsheet to load book and inventory details.")
        else:
            unmatched_rows, unmatched_quantity = unmatched_website_response_totals()
            if unmatched_rows:
                st.warning(
                    f"{unmatched_rows} synced website-response row(s), totaling "
                    f"{unmatched_quantity} copies, do not match an active catalogue entry "
                    "by book name and language. They are excluded from catalogue inventory "
                    "totals; align the names and languages in the Lists and responses tabs."
                )
            variants = list_book_variants(include_response_totals=True)
            if not variants.empty:
                inventory, warnings = catalogue_inventory_snapshot(snapshot, variants)
                for warning in warnings:
                    st.warning(warning)
                st.markdown("#### Inventory snapshot")
                inventory_metrics = (
                    ("Starting stock (Lists)", "stock", "count"),
                    ("Stock value", "stock_value", "currency"),
                    ("Books distributed (responses)", "response_books_distributed", "count"),
                    ("Balance books (calculated)", "response_balance_books", "count"),
                )
                missing_metric_values = []
                for column, (label, field, value_type) in zip(
                    st.columns(len(inventory_metrics)), inventory_metrics
                ):
                    value, populated_count, row_count = summarize_inventory_values(
                        inventory[field]
                    )
                    missing_count = row_count - populated_count
                    if missing_count:
                        missing_metric_values.append(f"{label}: {missing_count}")
                    if value is None:
                        formatted_value = "—"
                    elif value_type == "currency":
                        formatted_value = f"₹{value:,.2f}"
                    else:
                        formatted_value = f"{value:,.0f}"
                    column.metric(label, formatted_value)
                    column.caption(
                        f"Values from {populated_count:,} of {row_count:,} active rows"
                    )
                if missing_metric_values:
                    st.caption(
                        "Totals include known values only; blank or unavailable values "
                        "are excluded, and a dash means none were available. Missing "
                        "active Lists rows — " + ", ".join(missing_metric_values) + "."
                    )
                st.caption(
                    "Starting stock and stock valuation come from the Stock and Stock Value "
                    "columns in Lists. Books distributed uses synced website responses "
                    "matched by book name and language; calculated balance is starting "
                    "stock minus those responses."
                )
            st.markdown("#### Lists sheet")
            st.dataframe(
                snapshot,
                use_container_width=True,
                hide_index=True,
            )

    def _render_devotees():
        _page_heading("People & goals", "Devotees and targets", "Keep your devotee directory and individual goals up to date.")
        sellers = list_sellers(include_inactive=True)
        with st.expander("Devotee directory", expanded=True):
            if sellers.empty:
                st.caption("No devotees have been added yet.")
            else:
                st.dataframe(
                    sellers.rename(
                        columns={
                            "seller_name": "Devotee",
                            "active": "Active",
                            "created_at": "Added",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        with st.expander("Add a devotee"):
            with st.form("add_seller_form", clear_on_submit=True):
                name = st.text_input("Devotee name")
                target = st.number_input(
                    "Individual target (points)",
                    min_value=0.0,
                    max_value=100_000_000.0,
                    value=0.0,
                    step=0.01,
                    format="%.2f",
                )
                if st.form_submit_button("Add devotee", type="primary"):
                    try:
                        add_seller(name)
                        set_seller_target(name, float(target))
                        st.success("Devotee added.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

        active_devotees = sellers[sellers["active"] == 1] if not sellers.empty else sellers
        if not active_devotees.empty:
            with st.expander("Update a devotee target"):
                chosen = st.selectbox("Devotee", active_devotees["seller_name"].tolist())
                targets = list_seller_targets()
                existing = targets[targets["seller_name"] == chosen]
                current = float(existing.iloc[0]["target_points"]) if not existing.empty else 0.0
                new_target = st.number_input(
                    "Target points",
                    min_value=0.0,
                    max_value=100_000_000.0,
                    value=current,
                    step=0.01,
                    format="%.2f",
                )
                if st.button("Save devotee target", type="primary"):
                    set_seller_target(chosen, float(new_target))
                    st.success("Devotee target saved.")
                    st.rerun()

        with st.expander("Devotee target progress"):
            leaders = leaderboard(include_all_active=True)
            if leaders.empty:
                st.caption("Progress will appear after devotees and sales are recorded.")
            else:
                st.dataframe(
                    _leaderboard_labels(leaders),
                    use_container_width=True,
                    hide_index=True,
                )


    def _render_settings():
        _page_heading(
            "Preferences & data",
            "Settings",
            "Manage targets, Google Sheets sync, preferences, and backups.",
        )
        settings = get_settings()
        persistent_settings = get_persistent_settings()
        persistent_setting_keys = set(persistent_settings)
        if persistent_setting_keys:
            st.info(
                "Some application settings are managed through Streamlit Secrets and "
                "cannot be saved here. Update [app_settings] in the Cloud Secrets editor "
                "and restart the app for those changes to take effect."
            )
        with st.expander("Targets and import preferences", expanded=True):
            persistent_target_keys = persistent_setting_keys & {
                "overall_target",
                "overall_target_start_date",
                "overall_target_end_date",
                "fallback_points",
            }
            if persistent_target_keys:
                st.caption(
                    "This section is read-only because at least one value is managed "
                    "through Streamlit Secrets."
                )
            target_start_date_enabled = st.checkbox(
                "Set a target start date",
                value=bool(settings.get("overall_target_start_date")),
                key="target_start_date_enabled",
                disabled=bool(persistent_target_keys),
            )
            target_end_date_enabled = st.checkbox(
                "Set a target end date",
                value=bool(settings.get("overall_target_end_date")),
                key="target_end_date_enabled",
                disabled=bool(persistent_target_keys),
            )
            with st.form("settings_form"):
                overall_target = st.number_input(
                    "Overall points target",
                    min_value=0.0,
                    max_value=1_000_000_000.0,
                    value=float(settings.get("overall_target", "0")),
                    step=0.01,
                    format="%.2f",
                    disabled=bool(persistent_target_keys),
                )
                target_start_date = st.date_input(
                    "Target start date",
                    value=(
                        date.fromisoformat(settings["overall_target_start_date"])
                        if settings.get("overall_target_start_date")
                        else date.today()
                    ),
                    disabled=bool(persistent_target_keys) or not target_start_date_enabled,
                    key="target_start_date",
                )
                target_end_date = st.date_input(
                    "Target end date",
                    value=(
                        date.fromisoformat(settings["overall_target_end_date"])
                        if settings.get("overall_target_end_date")
                        else date.today()
                    ),
                    disabled=bool(persistent_target_keys) or not target_end_date_enabled,
                    key="target_end_date",
                )
                st.caption(
                    "Target progress counts points within the selected dates, inclusive. "
                    "Leave a date unset to keep that side of the period open."
                )
                fallback_points = st.number_input(
                    "Fallback points for an unknown book",
                    min_value=0.0,
                    max_value=100_000.0,
                    value=float(settings.get("fallback_points", "1")),
                    step=0.01,
                    format="%.2f",
                    disabled=bool(persistent_target_keys),
                )
                if st.form_submit_button(
                    "Save preferences",
                    type="primary",
                    disabled=bool(persistent_target_keys),
                ):
                    try:
                        save_settings({
                            "overall_target": str(float(overall_target)),
                            "fallback_points": str(float(fallback_points)),
                            "overall_target_start_date": (
                                target_start_date.isoformat()
                                if target_start_date_enabled
                                else ""
                            ),
                            "overall_target_end_date": (
                                target_end_date.isoformat()
                                if target_end_date_enabled
                                else ""
                            ),
                        })
                        st.success("Preferences saved.")
                        st.rerun()
                    except (ValueError, OSError) as exc:
                        st.error(f"Could not save preferences: {exc}")

        with st.expander("Google Sheets sync schedule", expanded=True):
            sync_settings = get_settings()
            persistent_sync_keys = persistent_setting_keys & {
                "google_sheets_auto_sync",
                "google_sheets_sync_interval_minutes",
                "google_sheets_manual_sync",
            }
            if persistent_sync_keys:
                st.caption(
                    "This section is read-only because at least one value is managed "
                    "through Streamlit Secrets."
                )
            with st.form("google_sheets_sync_schedule_form"):
                auto_sync_enabled = st.checkbox(
                    "Automatically sync all configured tabs",
                    value=_google_sync_setting_enabled(
                        sync_settings, "google_sheets_auto_sync"
                    ),
                    disabled=bool(persistent_sync_keys),
                    help=(
                        "A full sync reads the Lists, responses, and submissions tabs, "
                        "validates the data, then applies it in one database transaction."
                    ),
                )
                sync_interval_minutes = st.number_input(
                    "Automatic sync interval (minutes)",
                    min_value=1,
                    max_value=1440,
                    value=int(
                        sync_settings.get(
                            "google_sheets_sync_interval_minutes", "5"
                        )
                    ),
                    step=1,
                    disabled=bool(persistent_sync_keys) or not auto_sync_enabled,
                    help="Allowed interval: 1 to 1440 minutes. The default is 5 minutes.",
                )
                manual_sync_enabled = st.checkbox(
                    "Allow manual sync from the catalogue and responses pages",
                    value=_google_sync_setting_enabled(
                        sync_settings, "google_sheets_manual_sync"
                    ),
                    disabled=bool(persistent_sync_keys),
                )
                st.caption(
                    "Automatic sync runs immediately when the first dashboard session "
                    "opens, then on the selected interval while a dashboard session is "
                    "open. It pauses when there are no active sessions. Manual sync is "
                    "controlled independently."
                )
                save_sync_schedule = st.form_submit_button(
                    "Save sync schedule",
                    type="primary",
                    disabled=bool(persistent_sync_keys),
                )
            if save_sync_schedule:
                try:
                    save_settings(
                        {
                            "google_sheets_auto_sync": auto_sync_enabled,
                            "google_sheets_sync_interval_minutes": int(
                                sync_interval_minutes
                            ),
                            "google_sheets_manual_sync": manual_sync_enabled,
                        }
                    )
                    _secure_action_feedback("Google Sheets sync schedule saved.")
                except (ValueError, OSError, sqlite3.Error) as exc:
                    st.error(f"Could not save the sync schedule: {exc}")

        with st.expander("Google Sheets connection", expanded=True):
            persistent_sheet_keys = persistent_setting_keys & {
                "spreadsheet_id",
                "lists_tab",
                "responses_tab",
                "submissions_tab",
            }
            st.info(
                "Google service-account credentials are read only from Streamlit Secrets "
                "and are never saved in the app database."
            )
            st.caption(
                "For durable settings on Streamlit Community Cloud, put the spreadsheet ID "
                "and tab names under [app_settings] in Cloud → App settings → Secrets. "
                "Values in Secrets are read-only here. Locally, settings can still be saved "
                "from this page to SQLite."
            )
            if persistent_sheet_keys:
                st.caption(
                    "The spreadsheet connection settings are managed through Streamlit "
                    "Secrets. Update [app_settings] and restart the app to change them."
                )
            st.warning(
                "This app has no separate user accounts or roles. Anyone who can use this "
                "dashboard can initiate syncs, so keep the Streamlit app private."
            )
            _render_secure_action_feedback()
            current_config = _google_sheet_config()
            try:
                secrets_are_configured = bool(_google_sheet_credentials())
            except ValueError as exc:
                secrets_are_configured = False
                st.error(f"Invalid Google service-account secret: {exc}")
            if secrets_are_configured:
                st.success("Google service-account credentials are available from Secrets.")
            else:
                st.info(
                    "No [google_service_account] entry was found in Streamlit Secrets."
                )

            with st.form("google_sheets_settings_form"):
                spreadsheet_id = st.text_input(
                    "Spreadsheet ID or Google Sheets URL",
                    value=current_config["spreadsheet_id"],
                    key="google_sheets_spreadsheet_id",
                    help="Paste the workbook URL or its ID. No workbook ID is embedded in the app.",
                    disabled=bool(persistent_sheet_keys),
                )
                lists_tab = st.text_input(
                    "Catalogue tab name",
                    value=current_config["lists_tab"],
                    key="google_sheets_lists_tab",
                    disabled=bool(persistent_sheet_keys),
                )
                responses_tab = st.text_input(
                    "Book responses tab name",
                    value=current_config["responses_tab"],
                    key="google_sheets_responses_tab",
                    disabled=bool(persistent_sheet_keys),
                )
                submissions_tab = st.text_input(
                    "Submission summaries tab name",
                    value=current_config["submissions_tab"],
                    key="google_sheets_submissions_tab",
                    disabled=bool(persistent_sheet_keys),
                )
                test_button, save_button, discard_button = st.columns(3)
                test_connection = test_button.form_submit_button("Test connection")
                save_connection = save_button.form_submit_button(
                    "Save settings",
                    type="primary",
                    disabled=bool(persistent_sheet_keys),
                )
                discard_changes = discard_button.form_submit_button("Discard")

            staged_config = {
                "spreadsheet_id": spreadsheet_id,
                "lists_tab": lists_tab,
                "responses_tab": responses_tab,
                "submissions_tab": submissions_tab,
            }
            if discard_changes:
                st.session_state.pop("_google_sheets_tested_config_hash", None)
                _secure_action_feedback(
                    "Unsaved Google Sheets changes were discarded.",
                    clear_keys=[
                        "google_sheets_spreadsheet_id",
                        "google_sheets_lists_tab",
                        "google_sheets_responses_tab",
                        "google_sheets_submissions_tab",
                    ],
                )
            config_fingerprint = _google_sheet_config_fingerprint(staged_config)
            if (
                st.session_state.get("_google_sheets_tested_config_hash")
                == config_fingerprint
            ):
                if persistent_sheet_keys:
                    st.info(
                        "The configured settings passed the read-only connection test "
                        "and are managed through Streamlit Secrets."
                    )
                else:
                    st.info(
                        "These staged settings passed the read-only connection test. "
                        "Select Save settings to apply them, or Discard."
                    )
            if test_connection:
                try:
                    service_account_info = _google_sheet_credentials()
                    if not service_account_info:
                        raise ValueError(
                            "Add the [google_service_account] table to Streamlit "
                            "Secrets before testing the connection."
                        )
                    reached = test_google_sheets_connection(
                        service_account_info=service_account_info,
                        spreadsheet_config=staged_config,
                    )
                    reached_message = (
                        f"Connected to spreadsheet {reached['spreadsheet_id']}; "
                        f"reached tabs: {', '.join(reached['tabs'])}. "
                        + (
                            "Settings are managed through Streamlit Secrets."
                            if persistent_sheet_keys
                            else "Save these tested settings or discard them."
                        )
                    )
                    st.session_state["_google_sheets_tested_config_hash"] = (
                        config_fingerprint
                    )
                    _secure_action_feedback(reached_message)
                except (ValueError, OSError, sqlite3.Error) as exc:
                    st.session_state.pop("_google_sheets_tested_config_hash", None)
                    _secure_action_feedback(
                        f"Google Sheets connection failed: {exc}",
                        is_error=True,
                    )
            if save_connection:
                if (
                    st.session_state.get("_google_sheets_tested_config_hash")
                    != config_fingerprint
                ):
                    st.session_state.pop(
                        "_google_sheets_tested_config_hash",
                        None,
                    )
                    _secure_action_feedback(
                        "Test the current spreadsheet settings before saving.",
                        is_error=True,
                    )
                try:
                    save_settings(staged_config)
                    st.session_state.pop(
                        "_google_sheets_tested_config_hash",
                        None,
                    )
                    _secure_action_feedback(
                        "Google Sheets settings saved. Credentials remain in Streamlit Secrets."
                    )
                except (ValueError, OSError, sqlite3.Error) as exc:
                    _secure_action_feedback(
                        f"Could not save Google Sheets settings: {exc}",
                        is_error=True,
                    )

            with st.expander("Streamlit Secrets format"):
                st.caption(
                    "To keep workbook settings, target values, fallback points, and sync "
                    "schedule across Cloud restarts, add or update this [app_settings] "
                    "table in the Cloud Secrets editor. Replace the spreadsheet ID."
                )
                st.code(
                    "[app_settings]\n"
                    'spreadsheet_id = "PASTE_SPREADSHEET_ID_HERE"\n'
                    'lists_tab = "Lists"\n'
                    'responses_tab = "responses"\n'
                    'submissions_tab = "submissions"\n'
                    "overall_target = 0\n"
                    'overall_target_start_date = ""\n'
                    'overall_target_end_date = ""\n'
                    "fallback_points = 1\n"
                    "google_sheets_auto_sync = true\n"
                    "google_sheets_sync_interval_minutes = 5\n"
                    "google_sheets_manual_sync = true",
                    language="toml",
                )
                st.caption(
                    "Values in [app_settings] are read-only in this app; edit Secrets and "
                    "restart to change them. Sales, devotee targets, and other SQLite data "
                    "are still temporary on Streamlit Community Cloud."
                )
                st.caption(
                    "Paste your actual Google service-account values in Streamlit Cloud's "
                    "Secrets editor (TOML format). Do not use the example placeholders."
                )
                st.code(
                    '[google_service_account]\n'
                    'type = "service_account"\n'
                    'project_id = "your-google-cloud-project-id"\n'
                    'private_key_id = "your-private-key-id"\n'
                    'private_key = """-----BEGIN PRIVATE KEY-----\n'
                    "PASTE_THE_REMAINING_PRIVATE_KEY_LINES_HERE\n"
                    '-----END PRIVATE KEY-----\n'
                    '"""\n'
                    'client_email = "your-service-account@your-project.iam.gserviceaccount.com"\n'
                    'client_id = "your-client-id"\n'
                    'token_uri = "https://oauth2.googleapis.com/token"',
                    language="toml",
                )
                st.caption(
                    "Do not include the spreadsheet ID in this block. In Google Cloud, "
                    "enable the Sheets API and share the workbook with client_email as a "
                    "Viewer. Restrict who can edit app Secrets. Rotate the service-account "
                    "key if it is ever exposed."
                )

        with st.expander("Data and backups"):
            st.caption(
                "Application data is stored on the server in the "
                f"`{DATA_DIR.name}` folder. The full server path is hidden. "
                "Streamlit Community Cloud does not preserve this SQLite data across "
                "restarts; download backups and use durable hosted storage for records "
                "that must not be lost."
            )
            st.download_button(
                "Download complete data backup",
                create_backup_zip(),
                "Haribol_Book_Distribution_Backup.zip",
                "application/zip",
                type="primary",
            )
            sales = list_sales()
            st.download_button(
                "Download all sales",
                export_sales_csv(_sales_display_frame(sales)),
                "book_sales_all.csv",
                "text/csv",
            )
            imports = list_imports()
            if not imports.empty:
                st.download_button(
                    "Download import history",
                    export_csv(imports),
                    "book_sales_import_history.csv",
                    "text/csv",
                )

        with st.expander("About this app"):
            st.markdown(f"**{APP_NAME.replace('_', ' ')}**")
            st.write(f"Version **{APP_VERSION}**")
            st.caption(
                "A hosted book distribution dashboard powered by Streamlit and SQLite, "
                "with catalogue and website responses synced from Google Sheets."
            )


    active_page = _sidebar_navigation()
    _render_google_sheets_auto_sync()
    if active_page == "Overview":
        _render_overview()
    elif active_page == "Sales records":
        _render_sales()
    elif active_page == "Response entry":
        _render_website_entries()
    elif active_page == "Book catalogue":
        _render_catalogue()
    elif active_page == "Devotees & targets":
        _render_devotees()
    else:
        _render_settings()

def main():
    if sys.argv[1:] == ["_serve"]:
        _serve()
        return

    parser = argparse.ArgumentParser(
        description="Start or stop the Haribol_Book_Distribution dashboard."
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("start", "stop"),
        default="start",
        help="start the dashboard (default) or stop it",
    )
    args = parser.parse_args()
    if args.action == "start":
        start()
    elif args.action == "stop":
        stop()
    else:
        _serve()


if __name__ == "__main__":
    if os.environ.get("HBD_STREAMLIT_RUN") == "1":
        _render_app()
    else:
        main()
