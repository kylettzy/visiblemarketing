import os
import json
import csv
import io
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import calendar
import smtplib
import re
import click
import tempfile
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from contextlib import closing
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import safe_join, secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    from authlib.integrations.flask_client import OAuth
except ImportError:
    OAuth = None

try:
    import psycopg
except ImportError:
    psycopg = None

DB_INTEGRITY_ERRORS = (
    (sqlite3.IntegrityError, psycopg.IntegrityError)
    if psycopg
    else (sqlite3.IntegrityError,)
)

APP_ROOT = Path(__file__).resolve().parent
load_dotenv(APP_ROOT / ".env")

IS_VERCEL = bool(os.environ.get("VERCEL"))
DEFAULT_RUNTIME_ROOT = Path("/tmp/vtic-store") if IS_VERCEL else APP_ROOT
RUNTIME_ROOT = Path(os.environ.get("VTIC_RUNTIME_ROOT", DEFAULT_RUNTIME_ROOT))
STATIC_ROOT = APP_ROOT / "static"
BUNDLED_UPLOAD_ROOT = APP_ROOT / "uploads"

# Vercel's deployed bundle is read-only. Flask's normal static handler is also
# bypassed by Vercel, so static assets are served explicitly from the bundle and
# runtime writes are confined to /tmp.
app = Flask(__name__, static_folder=None)
# Cloudflare terminates HTTPS before forwarding requests to Flask. Trust one
# proxy hop so generated URLs use the public HTTPS scheme and hostname.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["SECRET_KEY"] = os.environ.get(
    "VTIC_SECRET_KEY", "development-only-change-me"
)
DATABASE = Path(os.environ.get("VTIC_DATABASE_PATH", RUNTIME_ROOT / "vtic_store.db"))
POSTGRES_URL = (
    os.environ.get("POSTGRES_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
)
USING_POSTGRES = POSTGRES_URL.startswith(("postgresql://", "postgres://"))
UPLOAD_ROOT = RUNTIME_ROOT / "uploads"
MANUFACTURER_UPLOADS = UPLOAD_ROOT / "manufacturers"
PRODUCT_UPLOADS = UPLOAD_ROOT / "products"
ACCOUNT_UPLOADS = UPLOAD_ROOT / "accounts"
PORTFOLIO_UPLOADS = UPLOAD_ROOT / "portfolio"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm"}
app.config["MAX_CONTENT_LENGTH"] = 128 * 1024 * 1024
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("VTIC_PUBLIC_URL", "")
    .strip()
    .lower()
    .startswith("https://"),
    SESSION_REFRESH_EACH_REQUEST=True,
)
MANUFACTURER_UPLOADS.mkdir(parents=True, exist_ok=True)
PRODUCT_UPLOADS.mkdir(parents=True, exist_ok=True)
ACCOUNT_UPLOADS.mkdir(parents=True, exist_ok=True)
PORTFOLIO_UPLOADS.mkdir(parents=True, exist_ok=True)

oauth = OAuth(app) if OAuth else None
OAUTH_PROVIDERS = {
    "google": {
        "label": "Google",
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile"},
    },
    "facebook": {
        "label": "Facebook",
        "client_id": os.environ.get("FACEBOOK_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("FACEBOOK_CLIENT_SECRET", "").strip(),
        "access_token_url": "https://graph.facebook.com/oauth/access_token",
        "authorize_url": "https://www.facebook.com/dialog/oauth",
        "api_base_url": "https://graph.facebook.com/",
        "client_kwargs": {"scope": "email,public_profile"},
    },
    "apple": {
        "label": "Apple",
        "client_id": os.environ.get("APPLE_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("APPLE_CLIENT_SECRET", "").strip(),
        "server_metadata_url": "https://appleid.apple.com/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email name"},
    },
}

PUBLIC_BASE_URL = os.environ.get("VTIC_PUBLIC_URL", "").strip().rstrip("/")
if PUBLIC_BASE_URL and not PUBLIC_BASE_URL.startswith(("https://", "http://")):
    raise RuntimeError("VTIC_PUBLIC_URL must start with https:// or http://")

if oauth:
    for provider_name, provider_config in OAUTH_PROVIDERS.items():
        if provider_config["client_id"] and provider_config["client_secret"]:
            oauth.register(
                name=provider_name,
                **{key: value for key, value in provider_config.items() if key != "label"},
            )


def oauth_provider_status():
    """Return provider availability without exposing OAuth credentials."""
    return {
        name: bool(oauth and config["client_id"] and config["client_secret"])
        for name, config in OAUTH_PROVIDERS.items()
    }


def oauth_callback_url(provider):
    path = url_for("customer_oauth_callback", provider=provider)
    return f"{PUBLIC_BASE_URL}{path}" if PUBLIC_BASE_URL else url_for(
        "customer_oauth_callback", provider=provider, _external=True
    )


@app.route("/static/<path:filename>", endpoint="static")
def static_files(filename):
    return send_from_directory(STATIC_ROOT, filename)


@app.after_request
def prevent_stale_authenticated_pages(response):
    """Keep session-aware HTML headers in sync with the current login state."""
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "private, no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.vary.add("Cookie")
    return response


@app.route("/uploads/<kind>/<path:filename>")
def uploaded_file(kind, filename):
    upload_directories = {
        "manufacturers": MANUFACTURER_UPLOADS,
        "products": PRODUCT_UPLOADS,
        "accounts": ACCOUNT_UPLOADS,
        "portfolio": PORTFOLIO_UPLOADS,
    }
    directory = upload_directories.get(kind)
    if directory is None:
        abort(404)
    runtime_file = safe_join(directory, filename)
    if runtime_file and Path(runtime_file).is_file():
        return send_from_directory(directory, filename)
    if IS_VERCEL:
        return send_from_directory(BUNDLED_UPLOAD_ROOT / kind, filename)
    return send_from_directory(directory, filename)


class CompatibleRow(dict):
    """Mapping row that also preserves sqlite3.Row-style numeric access."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def postgres_row_factory(cursor):
    columns = [column.name for column in cursor.description]

    def make_row(values):
        return CompatibleRow(zip(columns, values))

    return make_row


POSTGRES_ID_TABLES = {
    "admins",
    "customers",
    "customer_identities",
    "activity_logs",
    "review_requests",
    "review_request_items",
    "review_request_messages",
    "review_request_materials",
    "calendar_events",
    "ai_conversations",
    "ai_messages",
    "ai_solution_options",
    "ai_solution_items",
    "products",
    "manufacturers",
    "portfolio_clients",
    "gallery_items",
    "portfolio_partner_groups",
    "portfolio_partners",
}


def postgres_sql(sql):
    statement = re.sub(r"\s+COLLATE\s+NOCASE", "", sql, flags=re.IGNORECASE)
    ignore_conflicts = bool(
        re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\b", statement, re.IGNORECASE)
    )
    statement = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        statement,
        flags=re.IGNORECASE,
    )
    statement = statement.replace(
        "GROUP_CONCAT(DISTINCT r.status)",
        "STRING_AGG(DISTINCT r.status::text, ',')",
    )
    statement = statement.replace(
        """GROUP_CONCAT(
                         review.id || ':' || review.status || ':' ||
                         COALESCE(review.service_scope, '') || ':' ||
                         COALESCE(review.site_survey_at, '')
                       )""",
        """STRING_AGG(
                         review.id::text || ':' || review.status || ':' ||
                         COALESCE(review.service_scope, '') || ':' ||
                         COALESCE(review.site_survey_at, ''), ','
                       )""",
    )
    statement = statement.replace("?", "%s")
    statement = re.sub(
        r"\bCURRENT_TIMESTAMP\b",
        "(CURRENT_TIMESTAMP::text)",
        statement,
        flags=re.IGNORECASE,
    )
    if ignore_conflicts and " ON CONFLICT " not in statement.upper():
        statement = statement.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return statement


def postgres_schema(script):
    schema = re.sub(r"\s+COLLATE\s+NOCASE", "", script, flags=re.IGNORECASE)
    schema = re.sub(
        r"\bid\s+INTEGER\s+PRIMARY\s+KEY\b",
        "id BIGSERIAL PRIMARY KEY",
        schema,
        flags=re.IGNORECASE,
    )
    # The legacy SQLite schema declares some references before their target
    # tables. Application-level validation is retained; constraints can be
    # introduced later through ordered migrations.
    schema = re.sub(
        r"^\s*FOREIGN KEY\s*\([^\n]+$", "", schema, flags=re.MULTILINE | re.IGNORECASE
    )
    schema = re.sub(r",\s*\)", "\n            )", schema)
    schema = re.sub(
        r"\bCURRENT_TIMESTAMP\b",
        "(CURRENT_TIMESTAMP::text)",
        schema,
        flags=re.IGNORECASE,
    )
    return schema


class PostgresCursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def __iter__(self):
        return iter(self.cursor)


class PostgresConnection:
    def __init__(self):
        if psycopg is None:
            raise RuntimeError(
                "PostgreSQL is configured but psycopg is not installed."
            )
        self.connection = psycopg.connect(
            POSTGRES_URL, row_factory=postgres_row_factory, connect_timeout=10
        )

    def execute(self, sql, parameters=()):
        statement = postgres_sql(sql)
        insert_match = re.match(
            r"\s*INSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
            statement,
            re.IGNORECASE,
        )
        returns_id = bool(
            insert_match
            and insert_match.group(1).lower() in POSTGRES_ID_TABLES
            and " RETURNING " not in statement.upper()
        )
        if returns_id:
            statement = statement.rstrip().rstrip(";") + " RETURNING id"
        cursor = self.connection.execute(statement, parameters)
        returned_row = cursor.fetchone() if returns_id else None
        lastrowid = returned_row["id"] if returned_row else None
        return PostgresCursor(cursor, lastrowid)

    def executemany(self, sql, parameters):
        cursor = self.connection.cursor()
        cursor.executemany(postgres_sql(sql), parameters)
        return PostgresCursor(cursor)

    def executescript(self, script):
        for statement in postgres_schema(script).split(";"):
            if statement.strip():
                self.connection.execute(statement)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self.connection.__exit__(exc_type, exc_value, traceback)

    def close(self):
        if not self.connection.closed:
            self.connection.commit()
            self.connection.close()


def get_db():
    if USING_POSTGRES:
        return PostgresConnection()
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def table_columns(database, table_name):
    if USING_POSTGRES:
        return {
            row["column_name"]
            for row in database.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = ?""",
                (table_name,),
            )
        }
    return {row[1] for row in database.execute(f"PRAGMA table_info({table_name})")}


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def parse_optional_csv_price(value):
    """Return a Philippine currency CSV price or None when blank/invalid."""
    normalized = (
        str(value or "")
        .replace("\ufeff", "")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("₱", "")
        .replace("PHP", "")
        .replace("Php", "")
        .replace("php", "")
        .replace(",", "")
        .strip()
    )
    # Some Windows/ANSI CSV exports cannot encode the peso sign and replace
    # only that leading currency character with "?" (for example ?83,700.00).
    if normalized.startswith("?"):
        normalized = normalized[1:].strip()
    blank_values = {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "none",
        "null",
        "tbd",
        "project pricing",
        "for quotation",
        "request quote",
    }
    if normalized.casefold() in blank_values:
        return None
    try:
        price = float(normalized)
    except ValueError:
        return None
    return price if price >= 0 else None


def password_strength_error(password):
    """Return a user-facing password rule error, or None when it is strong."""
    if len(password) < 12:
        return "Password must contain at least 12 characters."
    if not re.search(r"[A-Z]", password):
        return "Password must include at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must include at least one lowercase letter."
    if not re.search(r"\d", password):
        return "Password must include at least one number."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must include at least one symbol."
    return None


def hide_customer_pricing(products):
    """Return storefront-safe products without confidential commercial data."""
    safe_products = []
    for product in products:
        safe_product = dict(product)
        safe_product["price"] = None
        safe_product["source"] = "Pricing available after VTIC review"
        safe_products.append(safe_product)
    return safe_products


def storefront_products_for_viewer(products):
    """Keep commercial data for staff previews and hide it from customers."""
    return products if session.get("admin_id") else hide_customer_pricing(products)


def add_manufacturer_logos(products):
    with get_db() as database:
        logo_map = {
            row["name"].casefold(): row["logo_url"]
            for row in database.execute(
                "SELECT name, logo_url FROM manufacturers WHERE logo_url IS NOT NULL"
            )
        }
    for product in products:
        product["manufacturer_logo"] = logo_map.get(product["brand"].casefold())
    return products


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        with closing(get_db()) as database:
            refresh_expired_account_statuses(database)
            account = database.execute(
                "SELECT status FROM admins WHERE id = ?", (session["admin_id"],)
            ).fetchone()
        if not account or account["status"] != "active":
            session.clear()
            flash("Your administrator account is not active.", "error")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped_view


def customer_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("customer_id") and not session.get("admin_id"):
            return redirect(url_for("customer_login", next=request.full_path))
        account_type = "admins" if session.get("admin_id") else "customers"
        account_id = session.get("admin_id") or session.get("customer_id")
        with closing(get_db()) as database:
            refresh_expired_account_statuses(database)
            account = database.execute(
                f"SELECT status FROM {account_type} WHERE id = ?", (account_id,)
            ).fetchone()
        if not account or account["status"] != "active":
            session.clear()
            flash("Your account is not active. Contact VTIC for assistance.", "error")
            endpoint = "admin_login" if account_type == "admins" else "customer_login"
            return redirect(url_for(endpoint))
        return view(*args, **kwargs)

    return wrapped_view


def ai_conversation_owner():
    """Return the authenticated owner fields used by AI conversations."""
    if session.get("admin_id"):
        return {
            "customer_id": 0,
            "admin_id": session["admin_id"],
            "actor_type": "admin",
            "actor_id": session["admin_id"],
            "actor_name": session.get("admin_username", "admin"),
        }
    return {
        "customer_id": session["customer_id"],
        "admin_id": None,
        "actor_type": "customer",
        "actor_id": session["customer_id"],
        "actor_name": session.get("customer_email", "customer"),
    }


def ai_conversation_owner_clause(owner):
    if owner["admin_id"] is not None:
        return "admin_id = ?", owner["admin_id"]
    return "customer_id = ? AND admin_id IS NULL", owner["customer_id"]


def refresh_expired_account_statuses(database):
    for table in ("admins", "customers"):
        database.execute(
            f"""UPDATE {table}
                SET status = 'active', status_expires_at = NULL,
                    status_updated_at = CURRENT_TIMESTAMP
                WHERE status != 'active' AND status_expires_at IS NOT NULL
                  AND status_expires_at <= CURRENT_TIMESTAMP"""
        )


def account_status_expiration(amount, unit):
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid restriction duration.")
    if amount < 1 or amount > 1000 or unit not in {"hours", "days", "months", "years"}:
        raise ValueError("Choose a duration between 1 and 1,000.")
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    if unit == "hours":
        expires = now + timedelta(hours=amount)
    elif unit == "days":
        expires = now + timedelta(days=amount)
    else:
        months = amount if unit == "months" else amount * 12
        month_index = now.month - 1 + months
        year = now.year + month_index // 12
        month = month_index % 12 + 1
        day = min(now.day, calendar.monthrange(year, month)[1])
        expires = now.replace(year=year, month=month, day=day)
    return expires.strftime("%Y-%m-%d %H:%M:%S")


def superadmin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        if session.get("admin_role") != "superadmin":
            abort(403)
        with closing(get_db()) as database:
            refresh_expired_account_statuses(database)
            account = database.execute(
                "SELECT status FROM admins WHERE id = ?", (session["admin_id"],)
            ).fetchone()
        if not account or account["status"] != "active":
            session.clear()
            flash("Your administrator account is not active.", "error")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped_view


def ensure_csrf_token():
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_hex(24)
    return session["csrf_token"]


def log_activity(actor_type, actor_id, actor_name, action, details=""):
    with get_db() as database:
        database.execute(
            """INSERT INTO activity_logs
               (actor_type, actor_id, actor_name, action, details, ip_address)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                actor_type,
                actor_id,
                actor_name,
                action,
                details[:500],
                (request.headers.get("X-Forwarded-For", request.remote_addr or "")
                 .split(",")[0]
                 .strip())[:64],
            ),
        )


def validate_csrf():
    if not secrets.compare_digest(
        session.get("csrf_token", ""), request.form.get("csrf_token", "")
    ):
        abort(400, "Invalid security token")


def save_manufacturer_logo(upload):
    if not upload or not upload.filename:
        return None
    filename = secure_filename(upload.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Logo must be a PNG, JPG, JPEG, or WebP image.")
    stored_name = f"{secrets.token_hex(12)}.{extension}"
    upload.save(MANUFACTURER_UPLOADS / stored_name)
    return url_for(
        "uploaded_file", kind="manufacturers", filename=stored_name
    )


def save_product_image(upload):
    if not upload or not upload.filename:
        return None
    filename = secure_filename(upload.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Product image must be a PNG, JPG, JPEG, or WebP file.")
    stored_name = f"{secrets.token_hex(12)}.{extension}"
    upload.save(PRODUCT_UPLOADS / stored_name)
    return url_for("uploaded_file", kind="products", filename=stored_name)


def save_account_photo(upload):
    if not upload or not upload.filename:
        return None
    filename = secure_filename(upload.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Profile photo must be a PNG, JPG, JPEG, or WebP file.")
    stored_name = f"{secrets.token_hex(12)}.{extension}"
    upload.save(ACCOUNT_UPLOADS / stored_name)
    return url_for("uploaded_file", kind="accounts", filename=stored_name)


def save_portfolio_image(upload):
    if not upload or not upload.filename:
        return None
    filename = secure_filename(upload.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Portfolio image must be a PNG, JPG, JPEG, or WebP file.")
    stored_name = f"{secrets.token_hex(12)}.{extension}"
    upload.save(PORTFOLIO_UPLOADS / stored_name)
    return url_for("uploaded_file", kind="portfolio", filename=stored_name)


def save_portfolio_video(upload):
    if not upload or not upload.filename:
        return None
    filename = secure_filename(upload.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError("Gallery video must be an MP4 or WebM file.")
    stored_name = f"{secrets.token_hex(12)}.{extension}"
    upload.save(PORTFOLIO_UPLOADS / stored_name)
    return url_for("uploaded_file", kind="portfolio", filename=stored_name)


def p(
    id,
    brand,
    name,
    category,
    price=None,
    emoji="▣",
    description="Enterprise-grade IT solution.",
    source="Partner quotation",
    color="#e8f0ff",
):
    return {
        "id": id,
        "brand": brand,
        "name": name,
        "category": category,
        "price": price,
        "old": price,
        "rating": 4.9,
        "sold": "Business",
        "emoji": emoji,
        "description": description,
        "source": source,
        "color": color,
        "quote": price is None,
    }


PRODUCTS = [
    p(
        1,
        "Ubiquiti",
        "UniFi U6+ WiFi 6 Access Point",
        "Wireless",
        7490,
        "◉",
        "Dual-band WiFi 6 access point for offices.",
        "PH market reference",
    ),
    p(
        2,
        "Cisco",
        "CBS350-24T-4G 24-Port Managed Switch",
        "Switches",
        None,
        "▦",
        "24-port managed business switch with Layer 3 features.",
    ),
    p(
        3,
        "Ruijie",
        "Reyee RG-EG105G-P V2 PoE Cloud Router",
        "Routers",
        4990,
        "↯",
        "Cloud-managed five-port gigabit PoE router.",
        "PH market reference",
    ),
    p(
        4,
        "Aruba",
        "Instant On AP22 WiFi 6 Access Point",
        "Wireless",
        10500,
        "◉",
        "Business WiFi 6 access point with cloud management.",
    ),
    p(
        5,
        "Cambium Networks",
        "cnPilot e410 Enterprise Access Point",
        "Wireless",
        None,
        "◉",
        "802.11ac Wave 2 indoor access point.",
    ),
    p(
        6,
        "Sundray",
        "AP-S500 Enterprise Wireless Access Point",
        "Wireless",
        None,
        "◉",
        "Managed wireless access point for business environments.",
    ),
    p(
        7,
        "Ubiquiti",
        "UniFi Switch Lite 8 PoE",
        "Switches",
        6490,
        "▦",
        "Eight-port managed switch with four PoE+ ports.",
        "PH market reference",
    ),
    p(
        8,
        "Cisco",
        "Meraki MX68 Security Appliance",
        "Cybersecurity",
        None,
        "⬡",
        "Cloud-managed security and SD-WAN appliance.",
    ),
    p(
        9,
        "Fortinet",
        "FortiGate 40F Security Appliance",
        "Cybersecurity",
        None,
        "⬡",
        "Next-generation firewall with SD-WAN services.",
    ),
    p(
        10,
        "Sophos",
        "XGS 87 Security Appliance",
        "Cybersecurity",
        None,
        "⬡",
        "Desktop next-generation firewall for small businesses.",
    ),
    p(
        11,
        "Palo Alto Networks",
        "PA-440 NGFW",
        "Cybersecurity",
        None,
        "⬡",
        "Machine-learning powered next-generation firewall.",
    ),
    p(
        12,
        "WatchGuard",
        "Firebox T45",
        "Cybersecurity",
        None,
        "⬡",
        "Unified threat management firewall with secure SD-WAN.",
    ),
    p(
        13,
        "SonicWall",
        "TZ370 Secure Firewall",
        "Cybersecurity",
        None,
        "⬡",
        "Secure SD-Branch firewall with threat protection.",
    ),
    p(
        14,
        "Barracuda",
        "CloudGen Firewall F12",
        "Cybersecurity",
        None,
        "⬡",
        "Compact next-generation branch firewall.",
    ),
    p(
        15,
        "Sangfor",
        "Network Secure NGAF M5100",
        "Cybersecurity",
        None,
        "⬡",
        "AI-enabled next-generation application firewall.",
    ),
    p(
        16,
        "CyberArk",
        "Privileged Access Manager",
        "Cybersecurity",
        None,
        "⌾",
        "Enterprise privileged access management subscription.",
    ),
    p(
        17,
        "McAfee",
        "Endpoint Security Business License",
        "Cybersecurity",
        None,
        "⌾",
        "Business endpoint threat prevention license.",
    ),
    p(
        18,
        "Belden",
        "7814A Cat6 UTP Cable 305m",
        "Cabling",
        12500,
        "〰",
        "24AWG solid copper Cat6 indoor UTP cable, 305m.",
        "PCWORX Philippines · Aug 2026",
        "#fff1dc",
    ),
    p(
        19,
        "Panduit",
        "NetKey Cat6 UTP Patch Cord 2m",
        "Cabling",
        650,
        "〰",
        "Factory-terminated Cat6 UTP patch cord.",
        "PH market estimate",
        "#fff1dc",
    ),
    p(
        20,
        "Panduit",
        "NKPPA24FMY 24-Port Patch Panel",
        "Cabling",
        None,
        "▤",
        "NetKey flat 24-port modular patch panel, 1RU.",
    ),
    p(
        21,
        "3M",
        "Cat6 RJ45 Modular Plug 50-Pack",
        "Cabling",
        None,
        "⌁",
        "Category 6 plugs for structured cabling.",
    ),
    p(
        22,
        "Alantek",
        "Cat6 UTP Cable 305m",
        "Cabling",
        8500,
        "〰",
        "Four-pair solid copper structured LAN cable.",
        "PH procurement reference",
        "#fff1dc",
    ),
    p(
        23,
        "Belden",
        "FiberExpress OM3 LC-LC Patch Cord 3m",
        "Fiber",
        None,
        "∞",
        "Multimode OM3 duplex fiber optic patch cord.",
    ),
    p(
        24,
        "Panduit",
        "Opti-Core OS2 Fiber Cable",
        "Fiber",
        None,
        "∞",
        "Single-mode indoor/outdoor fiber backbone cable.",
    ),
    p(
        25,
        "Hikvision",
        "TVI Lite 4CH 2D2B 2MP ColorVu Kit",
        "CCTV",
        8350,
        "◉",
        "Four-channel ColorVu surveillance kit.",
        "PC Express · Aug 2026",
        "#e8f7f4",
    ),
    p(
        26,
        "Hikvision",
        "TVI ECO 8CH 4D4B 2MP Kit",
        "CCTV",
        9100,
        "◉",
        "Eight-channel HDTVI CCTV package.",
        "PC Express · Aug 2026",
        "#e8f7f4",
    ),
    p(
        27,
        "Dahua",
        "Hero B1 2MP WiFi Pan/Tilt Camera",
        "CCTV",
        1050,
        "◉",
        "1080p pan-and-tilt camera with night vision.",
        "PC Express · Aug 2026",
        "#e8f7f4",
    ),
    p(
        28,
        "Dahua",
        "B200 2MP WiFi Bullet Camera",
        "CCTV",
        1800,
        "◉",
        "Weather-ready 1080p WiFi bullet camera.",
        "PC Express · Aug 2026",
        "#e8f7f4",
    ),
    p(
        29,
        "GeoVision",
        "GV-TBL4810 4MP IP Bullet Camera",
        "CCTV",
        None,
        "◉",
        "Outdoor 4MP H.265 infrared IP camera.",
    ),
    p(
        30,
        "Honeywell",
        "35 Series 4MP IP Dome Camera",
        "CCTV",
        None,
        "◉",
        "Business surveillance camera with smart motion.",
    ),
    p(
        31,
        "3CX",
        "Professional Annual License",
        "Communications",
        None,
        "☎",
        "Software IP PBX for business voice and video.",
    ),
    p(
        32,
        "Panasonic",
        "KX-NS500 IP-PBX System",
        "Communications",
        None,
        "☎",
        "Hybrid IP-PBX for small and medium businesses.",
    ),
    p(
        33,
        "Avaya",
        "J179 IP Phone",
        "Communications",
        None,
        "☎",
        "Eight-line enterprise SIP desk phone.",
    ),
    p(
        34,
        "Motorola",
        "MOTOTRBO R2 Two-Way Radio",
        "Communications",
        None,
        "⌁",
        "Durable digital two-way radio.",
    ),
    p(
        35,
        "Zimbra",
        "Network Edition Mailbox License",
        "Communications",
        None,
        "✉",
        "Secure business email and collaboration license.",
    ),
    p(
        36,
        "Dell",
        "PowerEdge R360 Rack Server",
        "Servers & Cloud",
        None,
        "▰",
        "1U enterprise rack server.",
    ),
    p(
        37,
        "HPE",
        "ProLiant DL380 Gen11 Server",
        "Servers & Cloud",
        None,
        "▰",
        "2U enterprise compute platform.",
    ),
    p(
        38,
        "Microsoft",
        "Microsoft 365 Business Standard 1-Year",
        "Cloud Software",
        7995,
        "☁",
        "One-year productivity subscription per user.",
        "PH market reference",
        "#e9f4ff",
    ),
    p(
        39,
        "Microsoft",
        "Azure Cloud Services",
        "Servers & Cloud",
        None,
        "☁",
        "Custom Azure compute, storage, backup and migration.",
    ),
    p(
        40,
        "AWS",
        "Cloud Infrastructure Services",
        "Servers & Cloud",
        None,
        "☁",
        "Custom cloud architecture and managed services.",
    ),
    p(
        41,
        "VMware",
        "vSphere Foundation Subscription",
        "Cloud Software",
        None,
        "☁",
        "Virtualization platform for private cloud.",
    ),
    p(
        42,
        "IBM",
        "Storage FlashSystem 5045",
        "Storage",
        None,
        "▰",
        "Enterprise all-flash storage system.",
    ),
    p(
        43,
        "Dell EMC",
        "PowerVault ME5024 Storage Array",
        "Storage",
        None,
        "▰",
        "High-performance SAN/DAS storage array.",
    ),
    p(
        44,
        "SolarWinds",
        "Network Performance Monitor",
        "Network Management",
        None,
        "⌁",
        "Enterprise network performance monitoring.",
    ),
    p(
        45,
        "WhatsUp Gold",
        "Premium Network Monitoring License",
        "Network Management",
        None,
        "⌁",
        "Availability and performance monitoring platform.",
    ),
    p(
        46,
        "Fluke Networks",
        "LinkIQ Cable+Network Tester",
        "Tools",
        None,
        "⌁",
        "Cable and network validation tester.",
    ),
    p(
        47,
        "Extreme Networks",
        "5520-24X Managed Switch",
        "Switches",
        None,
        "▦",
        "High-performance universal edge switch.",
    ),
    p(
        48,
        "Supermicro",
        "SuperServer 1U Enterprise Server",
        "Servers & Cloud",
        None,
        "▰",
        "Configurable data center rack server.",
    ),
]

CATEGORIES = [
    "All",
    "Wireless",
    "Access Points",
    "Wireless Controllers",
    "Routers",
    "Switches",
    "Firewalls & Security Appliances",
    "Cybersecurity",
    "Endpoint Security",
    "Network Accessories",
    "Cabling",
    "Patch Panels",
    "Patch Cords",
    "UTP & LAN Cables",
    "Fiber",
    "Fiber Accessories",
    "Racks & Cabinets",
    "CCTV",
    "IP Cameras",
    "NVR & DVR",
    "CCTV Accessories",
    "Access Control",
    "Communications",
    "IP Phones",
    "Video Conferencing",
    "Servers & Cloud",
    "Cloud Software",
    "Storage",
    "Computers & Workstations",
    "Monitors & Displays",
    "Printers & Scanners",
    "UPS & Power",
    "Software & Licensing",
    "Network Management",
    "Tools",
    "General IT Accessories",
]

CATEGORY_ALIASES = {
    "accessory": "General IT Accessories",
    "accessories": "General IT Accessories",
    "it accessory": "General IT Accessories",
    "it accessories": "General IT Accessories",
    "access point": "Access Points",
    "ap": "Access Points",
    "aps": "Access Points",
    "wireless ap": "Access Points",
    "router": "Routers",
    "switch": "Switches",
    "firewall": "Firewalls & Security Appliances",
    "patch panel": "Patch Panels",
    "patch cord": "Patch Cords",
    "lan cable": "UTP & LAN Cables",
    "utp cable": "UTP & LAN Cables",
    "fiber accessory": "Fiber Accessories",
    "rack": "Racks & Cabinets",
    "cabinet": "Racks & Cabinets",
    "camera": "IP Cameras",
    "ip camera": "IP Cameras",
    "nvr": "NVR & DVR",
    "dvr": "NVR & DVR",
    "cctv accessory": "CCTV Accessories",
    "ip phone": "IP Phones",
    "ups": "UPS & Power",
    "license": "Software & Licensing",
    "licensing": "Software & Licensing",
}


def normalize_product_category(value):
    """Match common CSV category variants while preserving legitimate new ones."""
    category = " ".join(str(value or "").strip().split())
    if not category:
        return ""
    known_categories = {item.casefold(): item for item in CATEGORIES[1:]}
    key = category.casefold()
    return known_categories.get(key) or CATEGORY_ALIASES.get(key) or category


def get_catalog_categories(include_all=True):
    """Return configured categories plus any categories introduced by imports."""
    categories = list(CATEGORIES[1:])
    known = {item.casefold() for item in categories}
    with get_db() as database:
        imported = database.execute(
            """SELECT DISTINCT trim(category) AS category
               FROM products WHERE trim(category) != '' ORDER BY category COLLATE NOCASE"""
        )
        for row in imported:
            category = row["category"]
            if category.casefold() not in known:
                categories.append(category)
                known.add(category.casefold())
    return (["All"] + categories) if include_all else categories


def initialize_database():
    with get_db() as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL DEFAULT '',
                email TEXT,
                avatar_url TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'superadmin',
                status TEXT NOT NULL DEFAULT 'active',
                last_login_at TEXT,
                status_updated_at TEXT,
                status_expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                avatar_url TEXT,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                status_updated_at TEXT,
                status_expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS customer_identities (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                provider_subject TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (provider, provider_subject),
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY,
                actor_type TEXT NOT NULL,
                actor_id INTEGER,
                actor_name TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                ip_address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS review_requests (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                ai_solution_option_id INTEGER,
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                commercial_notes TEXT NOT NULL DEFAULT '',
                bom_document TEXT,
                proposal_document TEXT,
                admin_reviewed_by INTEGER,
                admin_reviewed_at TEXT,
                superadmin_approved_by INTEGER,
                superadmin_approved_at TEXT,
                customer_notified_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );
            CREATE TABLE IF NOT EXISTS review_request_items (
                id INTEGER PRIMARY KEY,
                request_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                brand TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL,
                FOREIGN KEY (request_id) REFERENCES review_requests(id)
            );
            CREATE TABLE IF NOT EXISTS review_request_solution_options (
                request_id INTEGER NOT NULL,
                option_id INTEGER NOT NULL,
                PRIMARY KEY (request_id, option_id),
                FOREIGN KEY (request_id) REFERENCES review_requests(id),
                FOREIGN KEY (option_id) REFERENCES ai_solution_options(id)
            );
            CREATE TABLE IF NOT EXISTS review_request_messages (
                id INTEGER PRIMARY KEY,
                request_id INTEGER NOT NULL,
                sender_type TEXT NOT NULL,
                sender_id INTEGER,
                sender_name TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES review_requests(id)
            );
            CREATE TABLE IF NOT EXISTS review_message_reads (
                message_id INTEGER NOT NULL,
                reader_type TEXT NOT NULL,
                reader_id INTEGER NOT NULL,
                read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (message_id, reader_type, reader_id),
                FOREIGN KEY (message_id) REFERENCES review_request_messages(id)
            );
            CREATE TABLE IF NOT EXISTS admin_conversation_preferences (
                admin_id INTEGER NOT NULL,
                request_id INTEGER NOT NULL,
                is_muted INTEGER NOT NULL DEFAULT 0,
                muted_until TEXT,
                is_archived INTEGER NOT NULL DEFAULT 0,
                is_blocked INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (admin_id, request_id),
                FOREIGN KEY (admin_id) REFERENCES admins(id),
                FOREIGN KEY (request_id) REFERENCES review_requests(id)
            );
            CREATE TABLE IF NOT EXISTS review_request_materials (
                id INTEGER PRIMARY KEY,
                request_id INTEGER NOT NULL,
                material_name TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 1,
                unit TEXT NOT NULL DEFAULT 'pc',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES review_requests(id)
            );
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY,
                request_id INTEGER,
                event_type TEXT NOT NULL DEFAULT 'meeting',
                title TEXT NOT NULL,
                customer_name TEXT NOT NULL DEFAULT '',
                customer_email TEXT NOT NULL DEFAULT '',
                starts_at TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES review_requests(id)
            );
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT 'New solution consultation',
                requirements_summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );
            CREATE TABLE IF NOT EXISTS ai_messages (
                id INTEGER PRIMARY KEY,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES ai_conversations(id)
            );
            CREATE TABLE IF NOT EXISTS ai_solution_options (
                id INTEGER PRIMARY KEY,
                conversation_id INTEGER NOT NULL,
                option_key TEXT NOT NULL,
                name TEXT NOT NULL,
                summary TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES ai_conversations(id)
            );
            CREATE TABLE IF NOT EXISTS ai_solution_items (
                id INTEGER PRIMARY KEY,
                option_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                reason TEXT NOT NULL,
                optional INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (option_id) REFERENCES ai_solution_options(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                brand TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL,
                description TEXT NOT NULL,
                source TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#e8f0ff',
                image_url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS manufacturers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                logo_url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS portfolio_clients (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                sector TEXT NOT NULL,
                image_url TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT '',
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS gallery_items (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Behind the scenes',
                description TEXT NOT NULL DEFAULT '',
                event_date TEXT,
                album_name TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL,
                media_type TEXT NOT NULL DEFAULT 'image',
                video_url TEXT NOT NULL DEFAULT '',
                is_album_cover INTEGER NOT NULL DEFAULT 0,
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS portfolio_partner_groups (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL COLLATE NOCASE UNIQUE,
                name TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS portfolio_partners (
                id INTEGER PRIMARY KEY,
                group_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                website_url TEXT NOT NULL DEFAULT '#',
                logo_url TEXT NOT NULL DEFAULT '',
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES portfolio_partner_groups(id)
            );
            CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
            CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
            """
        )
        gallery_columns = table_columns(database, "gallery_items")
        if "album_name" not in gallery_columns:
            database.execute(
                "ALTER TABLE gallery_items ADD COLUMN album_name TEXT NOT NULL DEFAULT ''"
            )
        if "media_type" not in gallery_columns:
            database.execute(
                "ALTER TABLE gallery_items ADD COLUMN media_type TEXT NOT NULL DEFAULT 'image'"
            )
        if "video_url" not in gallery_columns:
            database.execute(
                "ALTER TABLE gallery_items ADD COLUMN video_url TEXT NOT NULL DEFAULT ''"
            )
        if "is_album_cover" not in gallery_columns:
            database.execute(
                "ALTER TABLE gallery_items ADD COLUMN is_album_cover INTEGER NOT NULL DEFAULT 0"
            )
        manufacturer_columns = table_columns(database, "manufacturers")
        if "logo_url" not in manufacturer_columns:
            database.execute("ALTER TABLE manufacturers ADD COLUMN logo_url TEXT")
        admin_columns = table_columns(database, "admins")
        if "role" not in admin_columns:
            database.execute(
                "ALTER TABLE admins ADD COLUMN role TEXT NOT NULL DEFAULT 'superadmin'"
            )
        if "status" not in admin_columns:
            database.execute(
                "ALTER TABLE admins ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
            )
        if "last_login_at" not in admin_columns:
            database.execute("ALTER TABLE admins ADD COLUMN last_login_at TEXT")
        if "status_updated_at" not in admin_columns:
            database.execute("ALTER TABLE admins ADD COLUMN status_updated_at TEXT")
        if "status_expires_at" not in admin_columns:
            database.execute("ALTER TABLE admins ADD COLUMN status_expires_at TEXT")
        if "full_name" not in admin_columns:
            database.execute("ALTER TABLE admins ADD COLUMN full_name TEXT NOT NULL DEFAULT ''")
        if "email" not in admin_columns:
            database.execute("ALTER TABLE admins ADD COLUMN email TEXT")
        if "avatar_url" not in admin_columns:
            database.execute("ALTER TABLE admins ADD COLUMN avatar_url TEXT")
        database.execute("UPDATE admins SET role = 'superadmin' WHERE role IS NULL")
        customer_columns = table_columns(database, "customers")
        if "status" not in customer_columns:
            database.execute(
                "ALTER TABLE customers ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
            )
        if "status_updated_at" not in customer_columns:
            database.execute("ALTER TABLE customers ADD COLUMN status_updated_at TEXT")
        if "status_expires_at" not in customer_columns:
            database.execute("ALTER TABLE customers ADD COLUMN status_expires_at TEXT")
        if "avatar_url" not in customer_columns:
            database.execute("ALTER TABLE customers ADD COLUMN avatar_url TEXT")
        review_columns = table_columns(database, "review_requests")
        if "ai_solution_option_id" not in review_columns:
            database.execute(
                "ALTER TABLE review_requests ADD COLUMN ai_solution_option_id INTEGER"
            )
        review_additions = {
            "commercial_notes": "TEXT NOT NULL DEFAULT ''",
            "bom_document": "TEXT",
            "proposal_document": "TEXT",
            "admin_reviewed_by": "INTEGER",
            "admin_reviewed_at": "TEXT",
            "superadmin_approved_by": "INTEGER",
            "superadmin_approved_at": "TEXT",
            "customer_notified_at": "TEXT",
            "service_scope": "TEXT NOT NULL DEFAULT ''",
            "customer_scope_decided_at": "TEXT",
            "marketing_reviewed_by": "INTEGER",
            "marketing_reviewed_at": "TEXT",
            "technical_reviewed_by": "INTEGER",
            "technical_reviewed_at": "TEXT",
            "site_survey_at": "TEXT",
            "site_survey_location": "TEXT NOT NULL DEFAULT ''",
            "site_survey_notes": "TEXT NOT NULL DEFAULT ''",
            "assigned_marketing_admin_id": "INTEGER",
            "assigned_marketing_at": "TEXT",
        }
        for column, definition in review_additions.items():
            if column not in review_columns:
                database.execute(
                    f"ALTER TABLE review_requests ADD COLUMN {column} {definition}"
                )
        database.execute(
            "UPDATE review_requests SET status = 'submitted' WHERE status = 'pending'"
        )
        conversation_columns = table_columns(database, "ai_conversations")
        if "admin_id" not in conversation_columns:
            database.execute(
                "ALTER TABLE ai_conversations ADD COLUMN admin_id INTEGER"
            )
        if "conversation_type" not in conversation_columns:
            database.execute(
                "ALTER TABLE ai_conversations ADD COLUMN conversation_type TEXT NOT NULL DEFAULT 'advisor'"
            )
            database.execute(
                """UPDATE ai_conversations SET conversation_type = 'product'
                   WHERE title LIKE 'Product chat:%'"""
            )
        message_columns = table_columns(database, "review_request_messages")
        if "read_by_customer" not in message_columns:
            database.execute(
                "ALTER TABLE review_request_messages ADD COLUMN read_by_customer INTEGER NOT NULL DEFAULT 0"
            )
            database.execute(
                "UPDATE review_request_messages SET read_by_customer = 1 WHERE sender_type = 'customer'"
            )
        if "read_by_admin" not in message_columns:
            database.execute(
                "ALTER TABLE review_request_messages ADD COLUMN read_by_admin INTEGER NOT NULL DEFAULT 0"
            )
            database.execute(
                "UPDATE review_request_messages SET read_by_admin = 1 WHERE sender_type = 'admin'"
            )
        preference_columns = table_columns(database, "admin_conversation_preferences")
        if "muted_until" not in preference_columns:
            database.execute(
                "ALTER TABLE admin_conversation_preferences ADD COLUMN muted_until TEXT"
            )
        if database.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            database.executemany(
                """INSERT INTO products
                   (id, brand, name, category, price, description, source, color)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item["id"],
                        item["brand"],
                        item["name"],
                        item["category"],
                        item["price"],
                        item["description"],
                        item["source"],
                        item["color"],
                    )
                    for item in PRODUCTS
                ],
            )
        database.execute(
            """INSERT OR IGNORE INTO manufacturers (name)
               SELECT DISTINCT brand FROM products WHERE trim(brand) != ''"""
        )
        manufacturer_partner_logos = {
            "3CX": 21,
            "3M": 1,
            "Alantek": 2,
            "Aruba": 20,
            "Avaya": 27,
            "AWS": 53,
            "Barracuda": 34,
            "Belden": 3,
            "Cambium Networks": 19,
            "Cisco": 18,
            "CyberArk": 40,
            "Dahua": 41,
            "Dell": 11,
            "Dell EMC": 12,
            "Extreme Networks": 13,
            "Fluke Networks": 8,
            "Fortinet": 39,
            "GeoVision": 44,
            "Hikvision": 42,
            "Honeywell": 45,
            "HPE": 20,
            "IBM": 51,
            "McAfee": 38,
            "Microsoft": 49,
            "Motorola": 28,
            "Palo Alto Networks": 32,
            "Panasonic": 22,
            "Panduit": 4,
            "Ruijie": 16,
            "Sangfor": 7,
            "SolarWinds": 6,
            "SonicWall": 35,
            "Sophos": 30,
            "Sundray": 14,
            "Supermicro": 55,
            "Ubiquiti": 17,
            "VMware": 52,
            "WatchGuard": 33,
            "WhatsUp Gold": 5,
            "Zimbra": 29,
        }
        for manufacturer_name, partner_logo_position in manufacturer_partner_logos.items():
            database.execute(
                """UPDATE manufacturers
                   SET logo_url = ?
                   WHERE name = ? COLLATE NOCASE
                     AND (logo_url IS NULL OR TRIM(logo_url) = '')""",
                (
                    f"/uploads/portfolio/partners/partner-{partner_logo_position:02d}.png",
                    manufacturer_name,
                ),
            )
        admin_username = os.environ.get("VTIC_ADMIN_USERNAME", "admin")
        configured_admin_password = os.environ.get("VTIC_ADMIN_PASSWORD")
        admin_password = configured_admin_password or "ChangeMe-VTIC-2026!"
        bootstrap_admin = database.execute(
            "SELECT id FROM admins WHERE username = ? COLLATE NOCASE",
            (admin_username,),
        ).fetchone()
        if not bootstrap_admin:
            database.execute(
                "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                (admin_username, generate_password_hash(admin_password)),
            )
        elif configured_admin_password:
            # A deployment-level recovery password must also repair an existing
            # runtime database. This is essential on ephemeral serverless hosts,
            # where an older /tmp database can outlive the code that created it.
            database.execute(
                """UPDATE admins
                   SET password_hash = ?, status = 'active', status_expires_at = NULL
                   WHERE id = ?""",
                (
                    generate_password_hash(configured_admin_password),
                    bootstrap_admin["id"],
                ),
            )
        if not USING_POSTGRES:
            database.execute("PRAGMA optimize")


initialize_database()


@app.cli.command("reset-admin-password")
@click.option(
    "--username",
    default="admin",
    show_default=True,
    help="Administrator username to recover.",
)
@click.option(
    "--activate/--no-activate",
    default=True,
    show_default=True,
    help="Reactivate the administrator account while resetting it.",
)
@click.password_option(
    "--password",
    confirmation_prompt=True,
    help="New administrator password. Omit this option for a hidden prompt.",
)
def reset_admin_password_command(username, activate, password):
    """Reset an existing administrator password without modifying other data."""
    username = username.strip()
    if not username:
        raise click.ClickException("Administrator username cannot be empty.")
    if password_error := password_strength_error(password):
        raise click.ClickException(password_error)

    with get_db() as database:
        admin = database.execute(
            "SELECT id, username FROM admins WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if not admin:
            raise click.ClickException(
                f'Administrator "{username}" does not exist in {DATABASE}.'
            )
        if activate:
            database.execute(
                """UPDATE admins
                   SET password_hash = ?, status = 'active', status_expires_at = NULL
                   WHERE id = ?""",
                (generate_password_hash(password), admin["id"]),
            )
        else:
            database.execute(
                "UPDATE admins SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), admin["id"]),
            )

    click.echo(f'Password reset completed for administrator "{admin["username"]}".')


@app.context_processor
def inject_auth_context():
    catered_customer_count = 0
    if session.get("admin_id") and session.get("admin_role") in {"admin_marketing", "superadmin"}:
        with get_db() as database:
            if session.get("admin_role") == "admin_marketing":
                catered_customer_count = database.execute(
                    """SELECT COUNT(DISTINCT customer_id) FROM review_requests
                       WHERE assigned_marketing_admin_id = ?""",
                    (session["admin_id"],),
                ).fetchone()[0]
            else:
                catered_customer_count = database.execute(
                    """SELECT COUNT(*) FROM (
                         SELECT assigned_marketing_admin_id, customer_id
                         FROM review_requests
                         WHERE assigned_marketing_admin_id IS NOT NULL
                         GROUP BY assigned_marketing_admin_id, customer_id
                       )"""
                ).fetchone()[0]
    return {
        "csrf_token": ensure_csrf_token(),
        "ai_configured": bool(get_gemini_api_key()),
        "can_view_prices": bool(session.get("admin_id")),
        "catered_customer_count": catered_customer_count,
    }


@app.route("/login", methods=["GET", "POST"])
def customer_login():
    if session.get("customer_id"):
        return redirect(url_for("storefront"))
    ensure_csrf_token()
    if request.method == "POST":
        validate_csrf()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with get_db() as database:
            refresh_expired_account_statuses(database)
            customer = database.execute(
                "SELECT * FROM customers WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
        if customer and check_password_hash(customer["password_hash"], password):
            if customer["status"] != "active":
                message = f"This account is {customer['status']}. Contact VTIC for assistance."
                if request.headers.get("X-Requested-With") == "fetch":
                    return jsonify(ok=False, message=message, fields=["email"]), 403
                flash(
                    message,
                    "error",
                )
                return render_template(
                    "customer_login.html", oauth_status=oauth_provider_status()
                )
            session.clear()
            session.permanent = request.form.get("remember_me") == "1"
            session["customer_id"] = customer["id"]
            session["customer_name"] = customer["full_name"]
            session["customer_email"] = customer["email"]
            session["csrf_token"] = secrets.token_hex(24)
            with get_db() as database:
                cursor = database.execute(
                    "UPDATE customers SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (customer["id"],),
                )
            log_activity("customer", customer["id"], customer["email"], "login")
            next_url = request.args.get("next", "")
            destination = next_url if next_url.startswith("/") else url_for("storefront")
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify(ok=True, redirect=destination)
            return redirect(destination)
        message = "Invalid email or password."
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(ok=False, message=message, fields=["email", "password"]), 401
        flash(message, "error")
    return render_template(
        "customer_login.html", oauth_status=oauth_provider_status()
    )


@app.route("/register", methods=["GET", "POST"])
def customer_register():
    if session.get("customer_id"):
        return redirect(url_for("storefront"))
    ensure_csrf_token()
    if request.method == "POST":
        validate_csrf()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        error_message = None
        error_fields = []
        if len(full_name) < 2:
            error_message, error_fields = "Enter your full name.", ["full_name"]
        elif "@" not in email or len(email) > 254:
            error_message, error_fields = "Enter a valid email address.", ["email"]
        elif password_error := password_strength_error(password):
            error_message, error_fields = password_error, ["password"]
        elif password != confirm_password:
            error_message, error_fields = "Password confirmation does not match.", ["confirm_password"]

        if error_message:
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify(ok=False, message=error_message, fields=error_fields), 400
            flash(error_message, "error")
        else:
            try:
                with get_db() as database:
                    cursor = database.execute(
                        "INSERT INTO customers (full_name, email, password_hash) VALUES (?, ?, ?)",
                        (full_name, email, generate_password_hash(password)),
                    )
                    customer_id = cursor.lastrowid
                log_activity("customer", customer_id, email, "register")
                if request.headers.get("X-Requested-With") == "fetch":
                    return jsonify(ok=True, redirect=url_for("customer_login"))
                flash("Account created. You can now sign in.", "success")
                return redirect(url_for("customer_login"))
            except DB_INTEGRITY_ERRORS:
                message = "An account already uses that email address."
                if request.headers.get("X-Requested-With") == "fetch":
                    return jsonify(ok=False, message=message, fields=["email"]), 409
                flash(message, "error")
    return render_template(
        "customer_register.html",
        oauth_status=oauth_provider_status(),
    )


def complete_customer_login(customer, action="oauth_login"):
    session.clear()
    session["customer_id"] = customer["id"]
    session["customer_name"] = customer["full_name"]
    session["customer_email"] = customer["email"]
    session["csrf_token"] = secrets.token_hex(24)
    with get_db() as database:
        database.execute(
            "UPDATE customers SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
            (customer["id"],),
        )
    log_activity("customer", customer["id"], customer["email"], action)


@app.route("/oauth/<provider>")
def customer_oauth_start(provider):
    config = OAUTH_PROVIDERS.get(provider)
    if not config:
        abort(404)
    if not oauth or not config["client_id"] or not config["client_secret"]:
        flash(
            f"{config['label']} sign-in is not configured yet. Use email registration for now.",
            "error",
        )
        return redirect(url_for("customer_register"))
    client = oauth.create_client(provider)
    redirect_uri = oauth_callback_url(provider)
    parameters = {"redirect_uri": redirect_uri}
    if provider == "apple":
        parameters["response_mode"] = "form_post"
    return client.authorize_redirect(**parameters)


@app.route("/oauth/<provider>/callback", methods=["GET", "POST"])
def customer_oauth_callback(provider):
    config = OAUTH_PROVIDERS.get(provider)
    if not config or not oauth:
        abort(404)
    client = oauth.create_client(provider)
    if not client:
        abort(404)
    try:
        token = client.authorize_access_token()
        if provider == "facebook":
            profile = client.get("me?fields=id,name,email").json()
            subject = str(profile.get("id", ""))
            email = str(profile.get("email", "")).strip().lower()
            full_name = str(profile.get("name", "")).strip()
        else:
            profile = token.get("userinfo") or client.parse_id_token(
                token, nonce=session.pop("_oauth_nonce", None)
            )
            subject = str(profile.get("sub", ""))
            email = str(profile.get("email", "")).strip().lower()
            full_name = str(profile.get("name", "")).strip()
            verified = profile.get("email_verified", True)
            if verified in (False, "false", "0"):
                raise ValueError("The provider did not verify this email address.")
        if not subject or "@" not in email:
            raise ValueError(
                f"{config['label']} did not provide a usable email address."
            )
        full_name = full_name or email.split("@", 1)[0].replace(".", " ").title()
        with get_db() as database:
            identity = database.execute(
                """SELECT customer.* FROM customer_identities identity
                   JOIN customers customer ON customer.id = identity.customer_id
                   WHERE identity.provider = ? AND identity.provider_subject = ?""",
                (provider, subject),
            ).fetchone()
            if identity:
                customer = identity
            else:
                customer = database.execute(
                    "SELECT * FROM customers WHERE email = ?", (email,)
                ).fetchone()
                if not customer:
                    cursor = database.execute(
                        """INSERT INTO customers (full_name, email, password_hash)
                           VALUES (?, ?, ?)""",
                        (
                            full_name[:120],
                            email,
                            generate_password_hash(secrets.token_urlsafe(48)),
                        ),
                    )
                    customer = database.execute(
                        "SELECT * FROM customers WHERE id = ?", (cursor.lastrowid,)
                    ).fetchone()
                database.execute(
                    """INSERT INTO customer_identities
                       (customer_id, provider, provider_subject) VALUES (?, ?, ?)""",
                    (customer["id"], provider, subject),
                )
        if customer["status"] != "active":
            flash(f"This customer account is {customer['status']}.", "error")
            return redirect(url_for("customer_login"))
        complete_customer_login(customer, f"oauth_login_{provider}")
        return redirect(url_for("storefront"))
    except Exception as error:
        app.logger.warning("%s OAuth sign-in failed: %s", provider, error)
        flash(
            f"{config['label']} sign-in could not be completed. Please try again or use email.",
            "error",
        )
        return redirect(url_for("customer_register"))


@app.route("/logout", methods=["POST"])
def customer_logout():
    if session.get("customer_id"):
        validate_csrf()
        log_activity(
            "customer",
            session["customer_id"],
            session.get("customer_email", "customer"),
            "logout",
        )
    session.clear()
    return redirect(url_for("customer_login"))


@app.route("/")
def home():
    return render_template("landing.html")


SOLUTION_PAGES = {
    "physical-security": {
        "index": "01",
        "name": "Physical Security",
        "eyebrow": "SEE EARLIER. RESPOND FASTER.",
        "headline": "Security intelligence for every site.",
        "summary": "Unify cameras, recording, access visibility and operational response in one professionally designed physical-security environment.",
        "description": "VTIC designs physical-security systems around real coverage requirements—not camera counts alone. We assess risk, fields of view, lighting, retention, network capacity and response workflows before specifying the system.",
        "features": ["IP cameras and intelligent video", "NVR, storage and video management", "Remote monitoring and alerts", "Structured cabling, racks and power", "Installation, commissioning and training", "Maintenance and lifecycle support"],
        "outcomes": [("Coverage", "Purpose-built camera placement"), ("Evidence", "Reliable recording and retention"), ("Response", "Faster operational awareness")],
        "categories": ["CCTV", "IP Cameras", "NVR & DVR", "CCTV Accessories"],
        "visual": "physical",
    },
    "information-security": {
        "index": "02", "name": "Information Security", "eyebrow": "DEFENSE ACROSS EVERY LAYER.",
        "headline": "Protect users, systems and critical data.",
        "summary": "A coordinated security architecture spanning the perimeter, endpoint, identity and cloud.",
        "description": "VTIC aligns security controls with your risk profile, operating model and existing infrastructure, then helps your team deploy and sustain them.",
        "features": ["Next-generation firewalls", "Endpoint protection", "Secure access and identity", "Email and data protection", "Security assessment", "Implementation and support"],
        "outcomes": [("Prevent", "Reduce the attack surface"), ("Detect", "Surface threats earlier"), ("Recover", "Strengthen operational resilience")],
        "categories": ["Cybersecurity", "Endpoint Security", "Firewalls & Security Appliances"], "visual": "security",
    },
    "wireless-connectivity": {
        "index": "03", "name": "Wireless Connectivity", "eyebrow": "COVERAGE WITHOUT COMPROMISE.",
        "headline": "Reliable wireless built for real demand.",
        "summary": "Enterprise Wi-Fi designed around users, devices, applications, capacity and the physical environment.",
        "description": "From predictive design through validation, VTIC builds managed wireless environments that remain secure and ready to scale.",
        "features": ["Wireless site surveys", "Indoor and outdoor access points", "Wireless controllers", "Point-to-point links", "Guest access", "Deployment and optimization"],
        "outcomes": [("Reach", "Consistent usable coverage"), ("Capacity", "Designed for device density"), ("Control", "Secure centralized management")],
        "categories": ["Wireless", "Access Points", "Wireless Controllers"], "visual": "wireless",
    },
    "communication": {
        "index": "04", "name": "Communication", "eyebrow": "CONNECT EVERY CONVERSATION.",
        "headline": "Communication that keeps teams moving.",
        "summary": "Voice, collaboration and unified communication systems for modern organizations.",
        "description": "VTIC connects people across offices, devices and working styles with communication platforms designed for clarity and continuity.",
        "features": ["IP telephony", "Unified communications", "Video conferencing", "Contact-center systems", "Messaging platforms", "Deployment and support"],
        "outcomes": [("Clarity", "Dependable business voice"), ("Access", "Work across locations"), ("Continuity", "Keep teams connected")],
        "categories": ["Communications", "Video Conferencing"], "visual": "communication",
    },
    "technology-backbone": {
        "index": "05", "name": "Technology Backbone", "eyebrow": "THE FOUNDATION FOR EVERYTHING.",
        "headline": "Infrastructure engineered to carry the business.",
        "summary": "Switching, routing, structured cabling, fiber and data-center foundations delivered as one system.",
        "description": "We connect the physical and logical layers so performance, manageability and future expansion are considered from day one.",
        "features": ["Enterprise switching and routing", "Structured copper cabling", "Fiber backbone", "Racks and cabinets", "Patch panels and accessories", "Testing and documentation"],
        "outcomes": [("Speed", "Correctly sized performance"), ("Order", "Documented infrastructure"), ("Scale", "Room for future growth")],
        "categories": ["Routers", "Switches", "Cabling", "Fiber", "Racks & Cabinets"], "visual": "backbone",
    },
    "cloud-computing": {
        "index": "06", "name": "Cloud Computing", "eyebrow": "COMPUTE WHERE IT WORKS BEST.",
        "headline": "A practical path to cloud and hybrid operations.",
        "summary": "Cloud, server, storage and virtualization choices aligned to the workload—not the trend.",
        "description": "VTIC helps organizations modernize infrastructure while balancing availability, control, performance and operating cost.",
        "features": ["Cloud readiness", "Servers and storage", "Virtualization", "Backup and recovery", "Hybrid architecture", "Migration and support"],
        "outcomes": [("Agility", "Deploy capacity faster"), ("Resilience", "Protect critical workloads"), ("Control", "Match platform to requirement")],
        "categories": ["Servers", "Storage", "Cloud Software"], "visual": "cloud",
    },
}

CLIENT_PORTFOLIO = [
    {
        "name": "2019 Southeast Asian Games",
        "short_name": "SEA Games 2019",
        "sector": "Events",
        "image": "images/clients/sea-games-2019.jpg",
        "scope": "Physical security and communication devices",
        "url": "https://2019seagames.com/",
    },
    {
        "name": "Philippine International Convention Center",
        "short_name": "PICC",
        "sector": "Government & Venues",
        "image": "images/clients/picc.jpg",
        "scope": "Wireless access points and network firewall",
        "url": "https://www.picc.gov.ph/",
    },
    {
        "name": "Dr. Emilio B. Espinosa Sr. Memorial State College",
        "short_name": "DEBESMSCAT",
        "sector": "Education",
        "image": "images/clients/debesmscat.jpg",
        "scope": "Technical support and CCTV",
        "url": "https://debesmscat.edu.ph/",
    },
    {
        "name": "University of Southern Mindanao",
        "short_name": "USM",
        "sector": "Education",
        "image": "images/clients/usm.jpg",
        "scope": "Wireless access points and aerial systems",
        "url": "https://www.usm.edu.ph/",
    },
    {
        "name": "Vista Mall",
        "short_name": "Vista Mall",
        "sector": "Retail",
        "image": "images/clients/vista-mall.jpg",
        "scope": "Managed wireless access points",
        "url": "https://www.vistamalls.com.ph/",
    },
    {
        "name": "Aqua Boracay",
        "short_name": "Aqua Boracay",
        "sector": "Hospitality",
        "image": "images/clients/aqua-boracay.jpg",
        "scope": "CCTV, structured cabling and grounding systems",
        "url": "https://www.aquaboracay.com/",
    },
    {
        "name": "Victoria Court",
        "short_name": "Victoria Court",
        "sector": "Hospitality",
        "image": "images/clients/victoria-court.png",
        "scope": "Firewall and endpoint security",
        "url": "https://www.victoriacourt.com/",
    },
]

PARTNER_PORTFOLIO = [
    {
        "slug": "infrastructure",
        "name": "Data Center & Network Infrastructure",
        "summary": "Cabling, compute, monitoring, testing and enterprise network foundations.",
        "partners": [
            ("3M", "https://www.3m.com/"), ("Alantek", "https://www.alantek.com/"),
            ("Belden", "https://www.belden.com/"), ("Panduit", "https://www.panduit.com/"),
            ("WhatsUp Gold", "https://www.progress.com/whatsup-gold"), ("SolarWinds", "https://www.solarwinds.com/"),
            ("Sangfor", "https://www.sangfor.com/"), ("Fluke Networks", "https://www.flukenetworks.com/"),
            ("HP", "https://www.hp.com/"), ("Apple", "https://www.apple.com/"),
            ("Dell", "https://www.dell.com/"), ("Dell EMC", "https://www.dell.com/en-us/dt/storage/index.htm"),
            ("Extreme Networks", "https://www.extremenetworks.com/"),
        ],
    },
    {
        "slug": "wireless",
        "name": "Wireless Network Systems",
        "summary": "Managed Wi-Fi, point-to-point connectivity and enterprise wireless control.",
        "partners": [
            ("Sundray", "https://www.sundray.com/"), ("XPossible", "#"),
            ("Ruijie Networks", "https://www.ruijienetworks.com/"), ("Ubiquiti", "https://www.ui.com/"),
            ("Cisco", "https://www.cisco.com/"), ("Cambium Networks", "https://www.cambiumnetworks.com/"),
            ("HPE Aruba Networking", "https://www.hpe.com/us/en/networking.html"),
        ],
    },
    {
        "slug": "communication",
        "name": "Communication Systems",
        "summary": "Voice, collaboration, messaging and enterprise communication platforms.",
        "partners": [
            ("3CX", "https://www.3cx.com/"), ("Panasonic", "https://holdings.panasonic/global/"),
            ("ShoreTel / Mitel", "https://www.mitel.com/"), ("Alcatel-Lucent Enterprise", "https://www.al-enterprise.com/"),
            ("NEC", "https://www.nec.com/"), ("Icom", "https://www.icomjapan.com/"),
            ("Avaya", "https://www.avaya.com/"), ("Motorola Solutions", "https://www.motorolasolutions.com/"),
            ("Zimbra", "https://www.zimbra.com/"),
        ],
    },
    {
        "slug": "network-security",
        "name": "Network & Information Security",
        "summary": "Perimeter defense, endpoint protection, identity security and secure access.",
        "partners": [
            ("Sophos", "https://www.sophos.com/"), ("Cisco", "https://www.cisco.com/"),
            ("Palo Alto Networks", "https://www.paloaltonetworks.com/"), ("WatchGuard", "https://www.watchguard.com/"),
            ("Barracuda", "https://www.barracuda.com/"), ("SonicWall", "https://www.sonicwall.com/"),
            ("Sangfor", "https://www.sangfor.com/"), ("24Online", "https://www.24online.in/"),
            ("McAfee", "https://www.mcafee.com/"), ("Fortinet", "https://www.fortinet.com/"),
            ("CyberArk", "https://www.cyberark.com/"),
        ],
    },
    {
        "slug": "physical-security",
        "name": "Physical Security",
        "summary": "Video surveillance, fire detection and integrated site-security platforms.",
        "partners": [
            ("Dahua Technology", "https://www.dahuasecurity.com/"), ("Hikvision", "https://www.hikvision.com/"),
            ("Kidde", "https://www.kidde.com/"), ("GeoVision", "https://www.geovision.com.tw/"),
            ("Honeywell", "https://www.honeywell.com/"),
        ],
    },
    {
        "slug": "cloud",
        "name": "Hosting & Cloud Computing",
        "summary": "Compute, storage, virtualization and public or hybrid cloud platforms.",
        "partners": [
            ("Apple", "https://www.apple.com/"), ("HP", "https://www.hp.com/"),
            ("Dell", "https://www.dell.com/"), ("Microsoft", "https://www.microsoft.com/"),
            ("Alibaba Cloud", "https://www.alibabacloud.com/"), ("IBM", "https://www.ibm.com/"),
            ("VMware", "https://www.vmware.com/"), ("Amazon Web Services", "https://aws.amazon.com/"),
            ("Microsoft Azure", "https://azure.microsoft.com/"), ("Supermicro", "https://www.supermicro.com/"),
            ("StorageCraft", "https://www.storagecraft.com/"),
        ],
    },
]

GALLERY_PORTFOLIO = [
    ("Alantek Structured Cabling Project", "Structured Cabling", "1377214_604647296260697_1789237869_n.jpg"),
    ("Alantek Structured Cabling Project", "Structured Cabling", "1375785_604647059594054_1267088196_n.jpg"),
    ("Alantek Structured Cabling Project", "Structured Cabling", "1374717_604646479594112_1011801746_n.jpg"),
    ("Alantek Structured Cabling", "Structured Cabling", "1381886_604637142928379_548915560_n.jpg"),
    ("Alantek Structured Cabling", "Structured Cabling", "1378771_604600406265386_1632712501_n-1.jpg"),
    ("Alantek Structured Cabling", "Structured Cabling", "539164_604599782932115_802772839_n.jpg"),
    ("94-Kilometer Point-to-Multipoint Backhaul", "Wireless Connectivity", "10710954_805534289505329_1969606592359628299_n.jpg"),
    ("Ubiquiti Access Point", "Wireless Connectivity", "5313_516284708430290_95426616_n.jpg"),
    ("Ubiquiti Access Point", "Wireless Connectivity", "599749_516284955096932_1782641302_n.jpg"),
    ("Ubiquiti Access Point", "Wireless Connectivity", "6806_516283101763784_687292251_n.jpg"),
    ("UBNT Point-to-Point", "Wireless Connectivity", "11140055_1013456482046441_4955113478435975178_n.jpg"),
    ("Ubiquiti WiFi Backhauling", "Wireless Connectivity", "312462_485192101539551_1810722419_n.jpg"),
    ("Ubiquiti WiFi AP Project", "Wireless Connectivity", "622288_440151659376929_119192134_o-1.jpg"),
    ("Alantek Structured Cabling", "Structured Cabling", "11072061_919853338073423_6405040444130753060_n.jpg"),
    ("Alantek Structured Cabling", "Structured Cabling", "11377124_919853088073448_170279434157696791_n.jpg"),
]

SOCIAL_GALLERY_ALBUM = [
    "787125037_1724684039662645_1739330955557713164_n.jpg",
    "787774002_1724684229662626_8600232777247085432_n.jpg",
    "787077051_1724684159662633_5659619453893339649_n.jpg",
    "788602785_1724684152995967_1548544710536154953_n.jpg",
    "788108927_1724684196329296_8182551738348804936_n.jpg",
    "778985406_1724684219662627_4473359736789472093_n.jpg",
    "778985495_1724684376329278_2664715687500646007_n.jpg",
    "787701810_1724684409662608_8236030915986521351_n.jpg",
    "788613707_1724684249662624_1755631153909057547_n.jpg",
    "786975596_1724684342995948_2755314318401834512_n.jpg",
    "786929319_1724684066329309_5000285991339149201_n.jpg",
    "786769097_1724684269662622_3601148537706991709_n.jpg",
    "778985402_1724684199662629_1804740502040774070_n.jpg",
    "787038614_1724684299662619_7972917705146374397_n.jpg",
]

SOCIAL_GALLERY_VIDEO = {
    "title": "Tagaytay Highlands 2025 President’s Cup",
    "category": "Events",
    "description": "Highlights from a day of great swings, friendly competition and memorable moments at the Tagaytay Highlands 2025 President’s Cup.",
    "event_date": "2025-01-01",
    "video_url": "/uploads/portfolio/gallery/videos/tagaytay-highlands-2025-presidents-cup.mp4",
}


def ensure_portfolio_seeded():
    """Copy the original portfolio into editable tables on first use."""
    with get_db() as database:
        if database.execute("SELECT COUNT(*) FROM portfolio_clients").fetchone()[0] == 0:
            database.executemany(
                """INSERT INTO portfolio_clients
                   (name, sector, image_url, scope, display_order)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (item["name"], item["sector"], item["image"], item["scope"], position)
                    for position, item in enumerate(CLIENT_PORTFOLIO, start=1)
                ],
            )
        if database.execute("SELECT COUNT(*) FROM portfolio_partner_groups").fetchone()[0] == 0:
            for group_position, group in enumerate(PARTNER_PORTFOLIO, start=1):
                cursor = database.execute(
                    """INSERT INTO portfolio_partner_groups
                       (slug, name, summary, display_order) VALUES (?, ?, ?, ?)""",
                    (group["slug"], group["name"], group["summary"], group_position),
                )
                database.executemany(
                    """INSERT INTO portfolio_partners
                       (group_id, name, website_url, display_order) VALUES (?, ?, ?, ?)""",
                    [
                        (cursor.lastrowid, name, website_url, partner_position)
                        for partner_position, (name, website_url) in enumerate(group["partners"], start=1)
                    ],
                )
        partner_logo_position = 1
        for group in PARTNER_PORTFOLIO:
            for name, _website_url in group["partners"]:
                database.execute(
                    """UPDATE portfolio_partners
                       SET logo_url = ?
                       WHERE name = ?
                         AND group_id = (
                           SELECT id FROM portfolio_partner_groups WHERE slug = ?
                         )
                         AND (logo_url IS NULL OR TRIM(logo_url) = '')""",
                    (
                        f"/uploads/portfolio/partners/partner-{partner_logo_position:02d}.png",
                        name,
                        group["slug"],
                    ),
                )
                partner_logo_position += 1
        if database.execute("SELECT COUNT(*) FROM gallery_items").fetchone()[0] == 0:
            database.executemany(
                """INSERT INTO gallery_items
                   (title, category, description, image_url, display_order)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        title,
                        category,
                        "From the VTIC project gallery.",
                        f"/uploads/portfolio/gallery/{filename}",
                        len(SOCIAL_GALLERY_ALBUM) + position + 1,
                    )
                    for position, (title, category, filename) in enumerate(
                        GALLERY_PORTFOLIO, start=1
                    )
                ],
            )
            database.executemany(
                """INSERT INTO gallery_items
                   (title, category, description, event_date, album_name, image_url, display_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        f"Confederation Annual Golf Tournament 2026 — Photo {position}",
                        "Events",
                        "VTIC provided the Visible Golf Tournament System and Event Management System for the Confederation Annual Golf Tournament 2026.",
                        "2026-08-27",
                        "Confederation Annual Golf Tournament 2026",
                        f"/uploads/portfolio/gallery/confederation-golf-2026/{filename}",
                        position + 1,
                    )
                    for position, filename in enumerate(SOCIAL_GALLERY_ALBUM, start=1)
                ],
            )
            database.execute(
                """INSERT INTO gallery_items
                   (title, category, description, event_date, album_name, image_url,
                    media_type, video_url, display_order)
                   VALUES (?, ?, ?, ?, '', '', 'video', ?, ?)""",
                (
                    SOCIAL_GALLERY_VIDEO["title"],
                    SOCIAL_GALLERY_VIDEO["category"],
                    SOCIAL_GALLERY_VIDEO["description"],
                    SOCIAL_GALLERY_VIDEO["event_date"],
                    SOCIAL_GALLERY_VIDEO["video_url"],
                    1,
                ),
            )


ensure_portfolio_seeded()


@app.route("/solutions/<slug>")
def solution_page(slug):
    solution = SOLUTION_PAGES.get(slug)
    if not solution:
        abort(404)
    solution = {
        **solution,
        "slug": slug,
        "video": f"videos/{slug}.mp4",
        "video_version": (
            "3"
            if slug in {
                "information-security",
                "technology-backbone",
                "communication",
                "cloud-computing",
            }
            else "2"
            if slug in {"physical-security", "wireless-connectivity"}
            else "1"
        ),
    }
    return render_template("solution_page.html", solution=solution, solutions=SOLUTION_PAGES)


@app.route("/clients")
def clients_page():
    with get_db() as database:
        clients = rows_to_dicts(
            database.execute(
                "SELECT * FROM portfolio_clients ORDER BY display_order, name COLLATE NOCASE"
            )
    )
    for client in clients:
        image_url = client["image_url"] or "images/technology-eye.webp"
        client["image_src"] = (
            image_url
            if image_url.startswith(("/", "http://", "https://"))
            else url_for("static", filename=image_url)
        )
    sectors = sorted({client["sector"] for client in clients})
    return render_template(
        "clients.html",
        clients=clients,
        sectors=sectors,
        solutions=SOLUTION_PAGES,
    )


@app.route("/partners")
def partners_page():
    with get_db() as database:
        groups = rows_to_dicts(
            database.execute(
                "SELECT * FROM portfolio_partner_groups ORDER BY display_order, name COLLATE NOCASE"
            )
        )
        partners = rows_to_dicts(
            database.execute(
                "SELECT * FROM portfolio_partners ORDER BY display_order, name COLLATE NOCASE"
            )
        )
    partners_by_group = {}
    for partner in partners:
        logo_url = partner["logo_url"]
        partner["logo_src"] = (
            logo_url
            if logo_url.startswith(("/", "http://", "https://"))
            else url_for("static", filename=logo_url)
        ) if logo_url else ""
        partners_by_group.setdefault(partner["group_id"], []).append(partner)
    for group in groups:
        group["partners"] = partners_by_group.get(group["id"], [])
    partner_count = len({partner["name"] for partner in partners})
    return render_template(
        "partners.html",
        partner_groups=groups,
        partner_count=partner_count,
        solutions=SOLUTION_PAGES,
    )


@app.route("/gallery")
def gallery_page():
    with get_db() as database:
        items = rows_to_dicts(
            database.execute(
                """SELECT * FROM gallery_items
                   ORDER BY display_order ASC, id DESC"""
            )
        )
    gallery_entries = []
    albums = {}
    for item in items:
        image_url = item["image_url"]
        item["image_src"] = (
            image_url
            if image_url.startswith(("/", "http://", "https://"))
            else url_for("static", filename=image_url)
        )
        video_url = item.get("video_url", "")
        item["video_src"] = (
            video_url
            if video_url.startswith(("/", "http://", "https://"))
            else url_for("static", filename=video_url)
        ) if video_url else ""
        item["poster_src"] = (
            f"{video_url.rsplit('.', 1)[0]}-poster.jpg"
            if item.get("media_type") == "video" and video_url
            else item["image_src"]
        )
        album_name = item.get("album_name", "").strip()
        key = f"album:{album_name}" if album_name else f"item:{item['id']}"
        if key not in albums:
            entry = {**item, "photos": [], "is_album": bool(album_name)}
            if album_name:
                entry["title"] = album_name
            albums[key] = entry
            gallery_entries.append(entry)
        albums[key]["photos"].append(
            {
                "src": item["image_src"],
                "video_src": item["video_src"],
                "type": item.get("media_type", "image"),
                "title": item["title"],
                "meta": f"{item['category']} · {item['event_date']}" if item["event_date"] else item["category"],
            }
        )
        if album_name and item.get("is_album_cover"):
            albums[key]["image_src"] = item["image_src"]
            albums[key]["video_src"] = item["video_src"]
            albums[key]["media_type"] = item.get("media_type", "image")
    categories = sorted({item["category"] for item in items})
    return render_template(
        "gallery.html",
        gallery_items=gallery_entries,
        gallery_categories=categories,
        solutions=SOLUTION_PAGES,
    )


@app.route("/storefront")
@customer_required
def storefront():
    with get_db() as database:
        catalog = rows_to_dicts(database.execute("SELECT * FROM products ORDER BY id"))
        partners = rows_to_dicts(
            database.execute(
                """SELECT m.id, m.name, m.logo_url, COUNT(p.id) AS product_count
                   FROM manufacturers m
                   INNER JOIN products p ON p.brand = m.name COLLATE NOCASE
                   GROUP BY m.id, m.name, m.logo_url
                   HAVING COUNT(p.id) > 0
                   ORDER BY m.name COLLATE NOCASE"""
            )
        )
    add_manufacturer_logos(catalog)
    catalog = storefront_products_for_viewer(catalog)
    return render_template(
        "index.html", products=catalog, categories=get_catalog_categories(), partners=partners
    )


@app.route("/products")
@customer_required
def products():
    category = request.args.get("category", "All")
    query = request.args.get("q", "").lower()
    brand = request.args.get("brand", "")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    per_page = 24
    sql = "SELECT * FROM products WHERE 1 = 1"
    parameters = []
    if category != "All":
        sql += " AND category = ?"
        parameters.append(category)
    if brand:
        sql += " AND brand = ?"
        parameters.append(brand)
    if query:
        sql += " AND lower(name || ' ' || brand || ' ' || category) LIKE ?"
        parameters.append(f"%{query}%")
    with get_db() as database:
        total_results = database.execute(
            f"SELECT COUNT(*) FROM ({sql})", parameters
        ).fetchone()[0]
        total_pages = max(1, (total_results + per_page - 1) // per_page)
        page = min(page, total_pages)
        paginated_sql = sql + " ORDER BY id DESC LIMIT ? OFFSET ?"
        results = rows_to_dicts(
            database.execute(
                paginated_sql,
                [*parameters, per_page, (page - 1) * per_page],
            )
        )
        brands = [
            row[0]
            for row in database.execute(
                "SELECT DISTINCT brand FROM products ORDER BY brand"
            )
        ]
    add_manufacturer_logos(results)
    results = storefront_products_for_viewer(results)
    return render_template(
        "products.html",
        products=results,
        category=category,
        query=request.args.get("q", ""),
        brand=brand,
        categories=get_catalog_categories(),
        brands=brands,
        page=page,
        total_pages=total_pages,
        total_results=total_results,
    )


@app.route("/product/<int:product_id>")
@customer_required
def product(product_id):
    with get_db() as database:
        row = database.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    item = add_manufacturer_logos([dict(row)])[0] if row else None
    if item:
        item = storefront_products_for_viewer([item])[0]
    return (
        (render_template("product.html", product=item), 200)
        if item
        else ("Product not found", 404)
    )


@app.route("/cart")
@customer_required
def cart():
    return render_template("cart.html")


@app.route("/api/products")
@customer_required
def api_products():
    with get_db() as database:
        catalog = rows_to_dicts(database.execute("SELECT * FROM products ORDER BY id"))
    add_manufacturer_logos(catalog)
    return jsonify(storefront_products_for_viewer(catalog))


AI_ADVISOR_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "requirements_summary": {"type": "string"},
        "needs_more_information": {"type": "boolean"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "rationale": {"type": "string"},
                    "products": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "quantity": {"type": "integer"},
                                "reason": {"type": "string"},
                                "optional": {"type": "boolean"},
                            },
                            "required": [
                                "product_id", "quantity", "reason", "optional"
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["key", "name", "summary", "rationale", "products"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "message", "requirements_summary", "needs_more_information",
        "questions", "options"
    ],
    "additionalProperties": False,
}


def get_ai_catalog():
    with get_db() as database:
        return rows_to_dicts(
            database.execute(
                """SELECT id, brand, name, category, description
                   FROM products ORDER BY category, brand, name"""
            )
        )


def raise_friendly_gemini_error(error):
    """Convert provider failures into safe, actionable Advisor messages."""
    error_code = getattr(error, "code", None) or getattr(error, "status_code", None)
    error_name = type(error).__name__.lower()
    error_text = str(error).lower()
    quota_error = (
        error_code == 429
        or "resourceexhausted" in error_name
        or "resource_exhausted" in error_text
        or "quota" in error_text
        or "rate limit" in error_text
    )
    authentication_error = (
        error_code in {401, 403}
        or "unauthenticated" in error_name
        or "permissiondenied" in error_name
        or "api key not valid" in error_text
        or "invalid api key" in error_text
    )
    if quota_error:
        if session.get("admin_id"):
            raise RuntimeError(
                "The Gemini API quota or rate limit has been reached. Check the "
                "Google AI Studio project quota, then try again."
            ) from error
        raise RuntimeError(
            "The AI Advisor is currently unavailable. Please submit your products "
            "for VTIC review or try again later."
        ) from error
    if authentication_error:
        if session.get("admin_id"):
            raise RuntimeError(
                "The configured Gemini API key was rejected. Update GEMINI_API_KEY "
                "in the server environment."
            ) from error
        raise RuntimeError(
            "The AI Advisor is currently unavailable. Please try again later."
        ) from error
    raise error


def create_gemini_client():
    """Create an SDK client, with a dependency-free REST fallback."""
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "The AI assistant is not configured yet. Add GEMINI_API_KEY to the "
            "server environment."
        )
    try:
        from google import genai
    except ImportError:
        return GeminiRestClient(api_key)
    else:
        return genai.Client(api_key=api_key)


class GeminiRestError(Exception):
    """Provider error compatible with the shared friendly-error mapper."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class GeminiRestResponse:
    def __init__(self, text):
        self.text = text


class GeminiRestModels:
    def __init__(self, api_key):
        self.api_key = api_key

    def generate_content(self, *, model, contents, config=None):
        """Call Gemini generateContent using only Python's standard library."""
        config = config or {}
        generation_config = {}
        config_fields = {
            "temperature": "temperature",
            "max_output_tokens": "maxOutputTokens",
            "response_mime_type": "responseMimeType",
            "response_json_schema": "responseJsonSchema",
        }
        for source_name, api_name in config_fields.items():
            if config.get(source_name) is not None:
                generation_config[api_name] = config[source_name]

        payload = {
            "contents": [{"role": "user", "parts": [{"text": contents}]}],
            "generationConfig": generation_config,
        }
        if config.get("system_instruction"):
            payload["systemInstruction"] = {
                "parts": [{"text": config["system_instruction"]}]
            }

        safe_model = urllib.parse.quote(model, safe="-._")
        api_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{safe_model}:generateContent"
        )
        api_request = urllib.request.Request(
            api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(api_request, timeout=90) as api_response:
                result = json.loads(api_response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                error_payload = json.loads(error.read().decode("utf-8"))
                message = error_payload.get("error", {}).get("message", str(error))
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = str(error)
            raise GeminiRestError(error.code, message) from error
        except urllib.error.URLError as error:
            raise GeminiRestError(None, f"Gemini connection failed: {error.reason}") from error

        text_parts = [
            part.get("text", "")
            for candidate in result.get("candidates", [])
            for part in candidate.get("content", {}).get("parts", [])
            if part.get("text")
        ]
        return GeminiRestResponse("".join(text_parts))


class GeminiRestClient:
    def __init__(self, api_key):
        self.models = GeminiRestModels(api_key)


def get_gemini_api_key():
    """Read the Gemini key, including the legacy field used by older installs."""
    return (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )


def gemini_conversation_prompt(history, context):
    """Convert stored provider-neutral messages into a bounded text transcript."""
    transcript = []
    for message in history[-12:]:
        role = "Customer" if message.get("role") == "user" else "VTIC assistant"
        transcript.append(f"{role}: {str(message.get('content', ''))[:4000]}")
    return f"{context}\n\nConversation:\n" + "\n".join(transcript)


def call_ai_solution_advisor(history, catalog):
    instructions = """You are VTIC's enterprise IT solution discovery assistant.
Ask concise clarifying questions when requirements are incomplete. Once enough
information exists, provide exactly three materially different options named
Essential, Recommended, and Enterprise. Recommend ONLY product_id values from
the supplied VTIC catalog. Never invent products, prices, stock, delivery dates,
compatibility guarantees, or certifications. Never reveal or estimate prices.
Explain that every design requires VTIC engineering and commercial review.
Use realistic quantities based on stated sites, users, ports, cameras and scope.
Mark enhancements that are not required as optional."""
    client = create_gemini_client()
    context = "Available VTIC catalog (prices intentionally omitted):\n" + json.dumps(
        catalog, ensure_ascii=False
    )
    try:
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
            contents=gemini_conversation_prompt(history, context),
            config={
                "system_instruction": instructions,
                "response_mime_type": "application/json",
                "response_json_schema": AI_ADVISOR_SCHEMA,
                "temperature": 0.2,
            },
        )
    except Exception as error:
        raise_friendly_gemini_error(error)
    if not response.text:
        raise RuntimeError("Gemini returned an empty response. Please try again.")
    return json.loads(response.text)


def call_storefront_product_chat(history, catalog, product=None):
    """Answer catalog questions without sending confidential pricing to the model."""
    focus = (
        f"The customer is currently viewing this product:\n{json.dumps(product, ensure_ascii=False)}"
        if product
        else "The customer is browsing the VTIC storefront, with no single product selected."
    )
    instructions = """You are the concise storefront assistant for VTIC, a Philippine
enterprise IT solutions provider. Answer questions using only the supplied VTIC catalog.
Help the customer understand product purpose, likely use cases, requirements, and sensible
questions for VTIC engineers. Never reveal, estimate, compare, or imply prices, margins,
stock, delivery dates, certifications, or compatibility guarantees. Do not invent products
or specifications. If catalog information is insufficient, say so clearly. For a complete
multi-product design, suggest opening the Solution Advisor. Keep answers under 180 words
unless the customer explicitly asks for detail. Every recommendation is subject to VTIC
engineering and commercial review."""
    client = create_gemini_client()
    context = (
        focus
        + "\nAvailable VTIC catalog (confidential fields omitted):\n"
        + json.dumps(catalog, ensure_ascii=False)
    )
    try:
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
            contents=gemini_conversation_prompt(history, context),
            config={
                "system_instruction": instructions,
                "temperature": 0.25,
                "max_output_tokens": 700,
            },
        )
    except Exception as error:
        raise_friendly_gemini_error(error)
    if not response.text:
        raise RuntimeError("Gemini returned an empty response. Please try again.")
    return response.text.strip()


def validate_ai_advice(advice, catalog):
    products_by_id = {product["id"]: product for product in catalog}
    safe_options = []
    for index, option in enumerate(advice.get("options", [])[:3]):
        safe_items = []
        used_ids = set()
        for item in option.get("products", [])[:30]:
            try:
                product_id = int(item["product_id"])
                quantity = int(item["quantity"])
            except (KeyError, TypeError, ValueError):
                continue
            if product_id not in products_by_id or product_id in used_ids:
                continue
            used_ids.add(product_id)
            product = products_by_id[product_id]
            safe_items.append(
                {
                    "product_id": product_id,
                    "quantity": max(1, min(quantity, 999)),
                    "reason": str(item.get("reason", ""))[:500],
                    "optional": bool(item.get("optional", False)),
                    "name": product["name"],
                    "brand": product["brand"],
                    "category": product["category"],
                }
            )
        if safe_items:
            safe_options.append(
                {
                    "key": str(option.get("key") or f"option-{index + 1}")[:40],
                    "name": str(option.get("name") or f"Option {index + 1}")[:80],
                    "summary": str(option.get("summary", ""))[:700],
                    "rationale": str(option.get("rationale", ""))[:1000],
                    "products": safe_items,
                }
            )
    return {
        "message": str(advice.get("message", ""))[:2000],
        "requirements_summary": str(advice.get("requirements_summary", ""))[:2000],
        "needs_more_information": bool(advice.get("needs_more_information", False)),
        "questions": [str(question)[:300] for question in advice.get("questions", [])[:8]],
        "options": safe_options,
    }


@app.route("/solution-advisor")
@customer_required
def solution_advisor():
    return render_template(
        "solution_advisor.html",
        ai_configured=bool(get_gemini_api_key()),
        anam_agent_id=os.environ.get(
            "ANAM_AGENT_ID", "854eaac4-bd3b-40f6-9f0c-26970e0a7c19"
        ).strip(),
    )


@app.route("/api/ai/advisor/conversations")
@customer_required
def ai_advisor_conversations():
    owner = ai_conversation_owner()
    owner_clause, owner_id = ai_conversation_owner_clause(owner)
    with get_db() as database:
        conversations = rows_to_dicts(
            database.execute(
                f"""SELECT id, title, requirements_summary, created_at, updated_at,
                           (SELECT COUNT(*) FROM ai_messages message
                            WHERE message.conversation_id = ai_conversations.id) AS message_count
                    FROM ai_conversations
                    WHERE {owner_clause} AND conversation_type = 'advisor'
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 100""",
                (owner_id,),
            )
        )
    return jsonify(conversations=conversations)


@app.route("/api/ai/advisor/conversations/<int:conversation_id>")
@customer_required
def ai_advisor_conversation(conversation_id):
    owner = ai_conversation_owner()
    owner_clause, owner_id = ai_conversation_owner_clause(owner)
    with get_db() as database:
        conversation = database.execute(
            f"""SELECT id, title, requirements_summary, created_at, updated_at
                FROM ai_conversations
                WHERE id = ? AND {owner_clause} AND conversation_type = 'advisor'""",
            (conversation_id, owner_id),
        ).fetchone()
        if not conversation:
            return jsonify(error="Conversation not found."), 404
        stored_messages = rows_to_dicts(
            database.execute(
                """SELECT role, content, created_at FROM ai_messages
                   WHERE conversation_id = ? ORDER BY id""",
                (conversation_id,),
            )
        )
        option_rows = rows_to_dicts(
            database.execute(
                """SELECT id, option_key AS key, name, summary, rationale
                   FROM ai_solution_options
                   WHERE conversation_id = ? ORDER BY id""",
                (conversation_id,),
            )
        )
        item_rows = rows_to_dicts(
            database.execute(
                """SELECT item.option_id, item.product_id, item.quantity,
                          item.reason, item.optional, product.name,
                          product.brand, product.category
                   FROM ai_solution_items item
                   JOIN products product ON product.id = item.product_id
                   WHERE item.option_id IN (
                       SELECT id FROM ai_solution_options WHERE conversation_id = ?
                   ) ORDER BY item.id""",
                (conversation_id,),
            )
        )
    items_by_option = {}
    for item in item_rows:
        item["optional"] = bool(item["optional"])
        items_by_option.setdefault(item.pop("option_id"), []).append(item)
    for option in option_rows:
        option["products"] = items_by_option.get(option["id"], [])
    return jsonify(
        conversation=dict(conversation),
        messages=stored_messages,
        options=option_rows,
    )


@app.route("/api/ai/advisor", methods=["POST"])
@customer_required
def ai_advisor_message():
    owner = ai_conversation_owner()
    owner_clause, owner_id = ai_conversation_owner_clause(owner)
    payload = request.get_json(silent=True) or {}
    if not secrets.compare_digest(
        session.get("csrf_token", ""), request.headers.get("X-CSRF-Token", "")
    ):
        abort(400, "Invalid security token")
    message = str(payload.get("message", "")).strip()
    if not message or len(message) > 4000:
        return jsonify(error="Enter a message between 1 and 4,000 characters."), 400
    conversation_id = payload.get("conversation_id")

    with get_db() as database:
        conversation = None
        if conversation_id:
            conversation = database.execute(
                f"SELECT * FROM ai_conversations WHERE id = ? AND {owner_clause}",
                (conversation_id, owner_id),
            ).fetchone()
            if not conversation:
                return jsonify(error="Conversation not found."), 404
        else:
            cursor = database.execute(
                """INSERT INTO ai_conversations
                   (customer_id, admin_id, title, conversation_type)
                   VALUES (?, ?, ?, 'advisor')""",
                (owner["customer_id"], owner["admin_id"], message[:100]),
            )
            conversation_id = cursor.lastrowid
        database.execute(
            "INSERT INTO ai_messages (conversation_id, role, content) VALUES (?, 'user', ?)",
            (conversation_id, message),
        )
        stored_messages = rows_to_dicts(
            database.execute(
                """SELECT role, content FROM ai_messages
                   WHERE conversation_id = ? ORDER BY id DESC LIMIT 12""",
                (conversation_id,),
            )
        )[::-1]

    history = [
        {"role": row["role"], "content": row["content"]}
        for row in stored_messages
    ]
    catalog = get_ai_catalog()
    try:
        advice = validate_ai_advice(call_ai_solution_advisor(history, catalog), catalog)
    except RuntimeError as error:
        return jsonify(error=str(error), conversation_id=conversation_id), 503
    except Exception:
        app.logger.exception("AI solution advisor request failed")
        return jsonify(
            error="The AI advisor is temporarily unavailable. Please try again.",
            conversation_id=conversation_id,
        ), 502

    with get_db() as database:
        database.execute(
            "INSERT INTO ai_messages (conversation_id, role, content) VALUES (?, 'assistant', ?)",
            (conversation_id, advice["message"]),
        )
        database.execute(
            """UPDATE ai_conversations SET requirements_summary = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (advice["requirements_summary"], conversation_id),
        )
        database.execute(
            "DELETE FROM ai_solution_items WHERE option_id IN (SELECT id FROM ai_solution_options WHERE conversation_id = ?)",
            (conversation_id,),
        )
        database.execute(
            "DELETE FROM ai_solution_options WHERE conversation_id = ?",
            (conversation_id,),
        )
        for option in advice["options"]:
            cursor = database.execute(
                """INSERT INTO ai_solution_options
                   (conversation_id, option_key, name, summary, rationale)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    conversation_id, option["key"], option["name"],
                    option["summary"], option["rationale"]
                ),
            )
            option["id"] = cursor.lastrowid
            database.executemany(
                """INSERT INTO ai_solution_items
                   (option_id, product_id, quantity, reason, optional)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        option["id"], item["product_id"], item["quantity"],
                        item["reason"], int(item["optional"])
                    )
                    for item in option["products"]
                ],
            )
    log_activity(
        owner["actor_type"], owner["actor_id"], owner["actor_name"],
        "ai_advisor_message", f"Conversation #{conversation_id}"
    )
    return jsonify(conversation_id=conversation_id, **advice)


@app.route("/api/ai/product-chat", methods=["POST"])
@customer_required
def storefront_product_chat():
    owner = ai_conversation_owner()
    owner_clause, owner_id = ai_conversation_owner_clause(owner)

    payload = request.get_json(silent=True) or {}
    if not secrets.compare_digest(
        session.get("csrf_token", ""), request.headers.get("X-CSRF-Token", "")
    ):
        abort(400, "Invalid security token")

    message = str(payload.get("message", "")).strip()
    if not message or len(message) > 2000:
        return jsonify(error="Enter a message between 1 and 2,000 characters."), 400

    product = None
    product_id = payload.get("product_id")
    if product_id not in (None, ""):
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return jsonify(error="Invalid product."), 400
        with get_db() as database:
            row = database.execute(
                """SELECT id, brand, name, category, description
                   FROM products WHERE id = ?""",
                (product_id,),
            ).fetchone()
        if not row:
            return jsonify(error="Product not found."), 404
        product = dict(row)

    conversation_id = payload.get("conversation_id")
    with get_db() as database:
        if conversation_id:
            conversation = database.execute(
                f"""SELECT id FROM ai_conversations
                    WHERE id = ? AND {owner_clause} AND conversation_type = 'product'""",
                (conversation_id, owner_id),
            ).fetchone()
            if not conversation:
                return jsonify(error="Conversation not found."), 404
        else:
            title = f"Product chat: {product['name']}" if product else message[:100]
            cursor = database.execute(
                """INSERT INTO ai_conversations
                   (customer_id, admin_id, title, conversation_type)
                   VALUES (?, ?, ?, 'product')""",
                (owner["customer_id"], owner["admin_id"], title),
            )
            conversation_id = cursor.lastrowid

        database.execute(
            "INSERT INTO ai_messages (conversation_id, role, content) VALUES (?, 'user', ?)",
            (conversation_id, message),
        )
        stored_messages = rows_to_dicts(
            database.execute(
                """SELECT role, content FROM ai_messages
                   WHERE conversation_id = ? ORDER BY id DESC LIMIT 12""",
                (conversation_id,),
            )
        )[::-1]

    history = [
        {"role": row["role"], "content": row["content"]}
        for row in stored_messages
    ]
    try:
        answer = call_storefront_product_chat(history, get_ai_catalog(), product)
    except RuntimeError as error:
        return jsonify(error=str(error), conversation_id=conversation_id), 503
    except Exception:
        app.logger.exception("Storefront product assistant request failed")
        return jsonify(
            error="The AI assistant is temporarily unavailable. Please try again.",
            conversation_id=conversation_id,
        ), 502

    with get_db() as database:
        database.execute(
            "INSERT INTO ai_messages (conversation_id, role, content) VALUES (?, 'assistant', ?)",
            (conversation_id, answer[:6000]),
        )
        database.execute(
            "UPDATE ai_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,),
        )
    log_activity(
        owner["actor_type"],
        owner["actor_id"],
        owner["actor_name"],
        "storefront_ai_chat",
        f"Conversation #{conversation_id}"
        + (f", product #{product_id}" if product else ""),
    )
    return jsonify(answer=answer, conversation_id=conversation_id)


@app.route("/api/ai/product-chat/conversations")
@customer_required
def storefront_product_chat_conversations():
    owner = ai_conversation_owner()
    owner_clause, owner_id = ai_conversation_owner_clause(owner)
    with get_db() as database:
        conversations = rows_to_dicts(
            database.execute(
                f"""SELECT id, title, created_at, updated_at,
                           (SELECT COUNT(*) FROM ai_messages message
                            WHERE message.conversation_id = ai_conversations.id) AS message_count,
                           (SELECT content FROM ai_messages message
                            WHERE message.conversation_id = ai_conversations.id
                            ORDER BY message.id DESC LIMIT 1) AS last_message
                    FROM ai_conversations
                    WHERE {owner_clause} AND conversation_type = 'product'
                    ORDER BY updated_at DESC, id DESC LIMIT 100""",
                (owner_id,),
            )
        )
    return jsonify(conversations=conversations)


@app.route("/api/ai/product-chat/conversations/<int:conversation_id>")
@customer_required
def storefront_product_chat_conversation(conversation_id):
    owner = ai_conversation_owner()
    owner_clause, owner_id = ai_conversation_owner_clause(owner)
    with get_db() as database:
        conversation = database.execute(
            f"""SELECT id, title, created_at, updated_at FROM ai_conversations
                WHERE id = ? AND {owner_clause} AND conversation_type = 'product'""",
            (conversation_id, owner_id),
        ).fetchone()
        if not conversation:
            return jsonify(error="Conversation not found."), 404
        stored_messages = rows_to_dicts(
            database.execute(
                """SELECT role, content, created_at FROM ai_messages
                   WHERE conversation_id = ? ORDER BY id""",
                (conversation_id,),
            )
        )
    return jsonify(conversation=dict(conversation), messages=stored_messages)


@app.route("/api/review-requests", methods=["POST"])
@customer_required
def create_review_request():
    if not session.get("customer_id"):
        return jsonify(
            error="Review requests must be submitted from a customer account."
        ), 403
    payload = request.get_json(silent=True) or {}
    if not secrets.compare_digest(
        session.get("csrf_token", ""), request.headers.get("X-CSRF-Token", "")
    ):
        abort(400, "Invalid security token")
    submitted_items = payload.get("items")
    notes = str(payload.get("notes", "")).strip()[:2000]
    submitted_option_ids = payload.get("ai_solution_option_ids", [])
    if not isinstance(submitted_option_ids, list):
        return jsonify(error="Invalid AI solution selections."), 400
    try:
        ai_solution_option_ids = list(
            dict.fromkeys(int(value) for value in submitted_option_ids)
        )
    except (TypeError, ValueError):
        return jsonify(error="Invalid AI solution selections."), 400
    if not isinstance(submitted_items, list) or not submitted_items:
        return jsonify(error="Your review cart is empty."), 400

    quantities = {}
    for item in submitted_items:
        try:
            product_id = int(item.get("id"))
            quantity = int(item.get("qty"))
        except (AttributeError, TypeError, ValueError):
            return jsonify(error="The cart contains invalid product data."), 400
        if product_id < 1 or quantity < 1 or quantity > 999:
            return jsonify(error="Product quantities must be between 1 and 999."), 400
        quantities[product_id] = min(999, quantities.get(product_id, 0) + quantity)

    placeholders = ",".join("?" for _ in quantities)
    with get_db() as database:
        if ai_solution_option_ids:
            option_placeholders = ",".join("?" for _ in ai_solution_option_ids)
            owned_option_ids = {
                row["id"]
                for row in database.execute(
                    f"""SELECT o.id FROM ai_solution_options o
                        JOIN ai_conversations c ON c.id = o.conversation_id
                        WHERE o.id IN ({option_placeholders})
                          AND c.customer_id = ?""",
                    (*ai_solution_option_ids, session["customer_id"]),
                )
            }
            if owned_option_ids != set(ai_solution_option_ids):
                return jsonify(error="One or more AI solution selections were not found."), 400
        products_by_id = {
            row["id"]: row
            for row in database.execute(
                f"SELECT id, name, brand, price FROM products WHERE id IN ({placeholders})",
                tuple(quantities),
            )
        }
        if len(products_by_id) != len(quantities):
            return jsonify(error="One or more products are no longer available."), 400
        cursor = database.execute(
            """INSERT INTO review_requests
               (customer_id, customer_name, customer_email, ai_solution_option_id, notes, status)
               VALUES (?, ?, ?, ?, ?, 'submitted')""",
            (
                session["customer_id"],
                session.get("customer_name", "Customer"),
                session.get("customer_email", ""),
                ai_solution_option_ids[0] if ai_solution_option_ids else None,
                notes,
            ),
        )
        request_id = cursor.lastrowid
        database.executemany(
            """INSERT INTO review_request_solution_options (request_id, option_id)
               VALUES (?, ?)""",
            [(request_id, option_id) for option_id in ai_solution_option_ids],
        )
        database.executemany(
            """INSERT INTO review_request_items
               (request_id, product_id, product_name, brand, quantity, unit_price)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    request_id,
                    product_id,
                    products_by_id[product_id]["name"],
                    products_by_id[product_id]["brand"],
                    quantity,
                    products_by_id[product_id]["price"],
                )
                for product_id, quantity in quantities.items()
            ],
        )
    log_activity(
        "customer",
        session["customer_id"],
        session.get("customer_email", "customer"),
        "review_request_submit",
        f"Request #{request_id} with {sum(quantities.values())} item(s)",
    )
    return jsonify(ok=True, request_id=request_id), 201


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    ensure_csrf_token()
    if request.method == "POST":
        validate_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_db() as database:
            refresh_expired_account_statuses(database)
            admin = database.execute(
                "SELECT * FROM admins WHERE username = ?", (username,)
            ).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            if admin["status"] != "active":
                message = f"This administrator account is {admin['status']}."
                if request.headers.get("X-Requested-With") == "fetch":
                    return jsonify(ok=False, message=message, fields=["username"]), 403
                flash(message, "error")
                return render_template("admin_login.html")
            session.clear()
            session.permanent = request.form.get("remember_me") == "1"
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            session["admin_role"] = admin["role"]
            session["csrf_token"] = secrets.token_hex(24)
            with get_db() as database:
                database.execute(
                    "UPDATE admins SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (admin["id"],),
                )
            log_activity("admin", admin["id"], admin["username"], "admin_login")
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify(ok=True, redirect=url_for("admin_dashboard"))
            return redirect(url_for("admin_dashboard"))
        message = "Invalid username or password."
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify(ok=False, message=message, fields=["username", "password"]), 401
        flash(message, "error")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
@login_required
def admin_logout():
    validate_csrf()
    log_activity(
        "admin",
        session["admin_id"],
        session.get("admin_username", "admin"),
        "admin_logout",
    )
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin/account", methods=["GET", "POST"])
@login_required
def admin_account():
    verified_at = session.get("credentials_verified_at")
    if request.method == "GET" and (
        not verified_at
        or datetime.now(timezone.utc).timestamp() - float(verified_at) > 600
    ):
        return redirect(url_for("admin_account_verify"))
    with get_db() as database:
        admin = database.execute(
            "SELECT * FROM admins WHERE id = ?", (session["admin_id"],)
        ).fetchone()
    if not admin:
        session.clear()
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        validate_csrf()
        current_password = request.form.get("current_password", "")
        username = request.form.get("username", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not check_password_hash(admin["password_hash"], current_password):
            flash("The current password is incorrect.", "error")
        elif len(username) < 3:
            flash("Username must contain at least 3 characters.", "error")
        elif new_password and (password_error := password_strength_error(new_password)):
            flash(password_error, "error")
        elif new_password != confirm_password:
            flash("The new password and confirmation do not match.", "error")
        else:
            password_hash = (
                generate_password_hash(new_password)
                if new_password
                else admin["password_hash"]
            )
            try:
                with get_db() as database:
                    database.execute(
                        "UPDATE admins SET username = ?, password_hash = ? WHERE id = ?",
                        (username, password_hash, admin["id"]),
                    )
                session["admin_username"] = username
                session["csrf_token"] = secrets.token_hex(24)
                log_activity(
                    "admin", admin["id"], username, "admin_credentials_update"
                )
                flash("Account credentials updated successfully.", "success")
                return redirect(url_for("admin_account"))
            except DB_INTEGRITY_ERRORS:
                flash("That username is already in use.", "error")

    return render_template(
        "admin_account.html", admin=dict(admin), account_section="credentials"
    )


@app.route("/admin/account/verify", methods=["GET", "POST"])
@login_required
def admin_account_verify():
    if request.method == "POST":
        validate_csrf()
        password = request.form.get("password", "")
        with closing(get_db()) as database:
            admin = database.execute(
                "SELECT password_hash FROM admins WHERE id = ?", (session["admin_id"],)
            ).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session["credentials_verified_at"] = datetime.now(timezone.utc).timestamp()
            return redirect(url_for("admin_account"))
        flash("Enter your current password to access credential changes.", "error")
    return render_template("admin_account_verify.html")


@app.route("/admin/account/appearance")
@login_required
def admin_account_appearance():
    return render_template("admin_account.html", account_section="appearance")


@app.route("/admin/account/database")
@superadmin_required
def admin_account_database():
    return render_template("admin_account.html", account_section="database")


@app.route("/admin/account/notifications")
@login_required
def admin_account_notifications():
    return render_template("admin_notifications.html")


@app.route("/admin/help")
@login_required
def admin_help():
    return render_template("admin_help.html")


@app.route("/admin/database/backup")
@superadmin_required
def admin_database_backup():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    temporary = tempfile.NamedTemporaryFile(
        prefix="vtic-backup-", suffix=".db", dir=RUNTIME_ROOT, delete=False
    )
    backup_path = Path(temporary.name)
    temporary.close()
    try:
        with closing(get_db()) as source, closing(
            sqlite3.connect(backup_path)
        ) as destination:
            source.backup(destination)
        response = send_file(
            backup_path,
            as_attachment=True,
            download_name=f"vtic-database-{timestamp}.db",
            mimetype="application/vnd.sqlite3",
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.call_on_close(lambda: backup_path.unlink(missing_ok=True))
        return response
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise


@app.route("/admin/database/restore", methods=["POST"])
@superadmin_required
def admin_database_restore():
    validate_csrf()
    uploaded = request.files.get("database_file")
    current_password = request.form.get("current_password", "")
    if not uploaded or not uploaded.filename:
        flash("Choose a VTIC database backup to restore.", "error")
        return redirect(url_for("admin_account_database"))
    if Path(uploaded.filename).suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        flash("The restore file must be a SQLite .db, .sqlite or .sqlite3 backup.", "error")
        return redirect(url_for("admin_account_database"))

    with closing(get_db()) as database:
        admin = database.execute(
            "SELECT password_hash FROM admins WHERE id = ?", (session["admin_id"],)
        ).fetchone()
    if not admin or not check_password_hash(admin["password_hash"], current_password):
        flash("The current superadmin password is incorrect.", "error")
        return redirect(url_for("admin_account_database"))

    restore_path = RUNTIME_ROOT / f"restore-{secrets.token_hex(12)}.db"
    uploaded.save(restore_path)
    required_tables = {"admins", "customers", "products", "manufacturers"}
    try:
        with closing(sqlite3.connect(restore_path)) as candidate:
            integrity = candidate.execute("PRAGMA quick_check").fetchone()
            tables = {
                row[0]
                for row in candidate.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not integrity or integrity[0] != "ok":
                raise ValueError("The uploaded database failed its integrity check.")
            missing_tables = sorted(required_tables - tables)
            if missing_tables:
                raise ValueError(
                    "The backup is missing required VTIC tables: "
                    + ", ".join(missing_tables)
                    + "."
                )
            active_superadmin = candidate.execute(
                """SELECT COUNT(*) FROM admins
                   WHERE role = 'superadmin' AND status = 'active'"""
            ).fetchone()[0]
            if active_superadmin < 1:
                raise ValueError(
                    "The backup must contain at least one active superadmin account."
                )

        recovery_directory = RUNTIME_ROOT / "backups"
        recovery_directory.mkdir(parents=True, exist_ok=True)
        recovery_path = recovery_directory / (
            "before-restore-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
        )
        with closing(get_db()) as source, closing(
            sqlite3.connect(recovery_path)
        ) as destination:
            source.backup(destination)

        os.replace(restore_path, DATABASE)
        for suffix in ("-wal", "-shm"):
            Path(str(DATABASE) + suffix).unlink(missing_ok=True)
        initialize_database()
        ensure_portfolio_seeded()
    except (sqlite3.DatabaseError, OSError, ValueError) as error:
        restore_path.unlink(missing_ok=True)
        flash(f"Database restore stopped: {error}", "error")
        return redirect(url_for("admin_account_database"))

    session.clear()
    flash("Database restored successfully. Sign in using an account from the backup.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin/accounts")
@superadmin_required
def admin_accounts():
    with get_db() as database:
        administrators = rows_to_dicts(
            database.execute(
                """SELECT id, username, full_name, email, avatar_url,
                          role, status, status_expires_at,
                          created_at, last_login_at
                   FROM admins
                   ORDER BY CASE role WHEN 'superadmin' THEN 0 ELSE 1 END,
                            COALESCE(NULLIF(full_name, ''), username) COLLATE NOCASE"""
            )
        )
        customers = rows_to_dicts(
            database.execute(
                """SELECT id, full_name, email, avatar_url, status, status_expires_at,
                          created_at, last_login_at
                   FROM customers ORDER BY full_name COLLATE NOCASE"""
            )
        )
    return render_template(
        "admin_accounts.html",
        administrators=administrators,
        customers=customers,
    )


@app.route(
    "/admin/accounts/<account_type>/<int:account_id>/status", methods=["POST"]
)
@superadmin_required
def admin_account_status(account_type, account_id):
    validate_csrf()
    if account_type not in {"admin", "customer"}:
        abort(404)
    status = request.form.get("status", "").strip().lower()
    if status not in {"active", "suspended", "banned"}:
        abort(400)
    duration_mode = request.form.get("duration_mode", "temporary").strip()
    status_expires_at = None
    if status != "active" and duration_mode != "permanent":
        try:
            status_expires_at = account_status_expiration(
                request.form.get("duration_amount"),
                request.form.get("duration_unit", "days"),
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("admin_accounts"))

    table = "admins" if account_type == "admin" else "customers"
    label_column = "username" if account_type == "admin" else "email"
    with get_db() as database:
        role_sql = ", role" if account_type == "admin" else ""
        account = database.execute(
            f"SELECT id, {label_column} AS label, status, status_expires_at{role_sql} "
            f"FROM {table} WHERE id = ?",
            (account_id,),
        ).fetchone()
        if not account:
            abort(404)
        if account_type == "admin" and account_id == session["admin_id"]:
            flash("You cannot change the status of your active account.", "error")
            return redirect(url_for("admin_accounts"))
        if (
            account_type == "admin"
            and account["role"] == "superadmin"
            and status != "active"
        ):
            active_superadmins = database.execute(
                "SELECT COUNT(*) FROM admins WHERE role = 'superadmin' AND status = 'active'"
            ).fetchone()[0]
            if active_superadmins <= 1:
                flash("At least one active superadmin must remain.", "error")
                return redirect(url_for("admin_accounts"))
        database.execute(
            f"""UPDATE {table} SET status = ?, status_expires_at = ?,
                status_updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (status, status_expires_at, account_id),
        )

    log_activity(
        "admin",
        session["admin_id"],
        session["admin_username"],
        f"{account_type}_status_update",
        f"{account['label']} (ID #{account_id}): {account['status']} to {status}"
        + (f" until {status_expires_at} UTC" if status_expires_at else " permanently" if status != "active" else ""),
    )
    duration_text = (
        f" until {status_expires_at} UTC" if status_expires_at else ""
    )
    flash(f"{account['label']} is now {status}{duration_text}.", "success")
    return redirect(url_for("admin_accounts"))


@app.route("/admin/accounts/new/<account_type>", methods=["GET", "POST"])
@superadmin_required
def admin_account_create(account_type):
    if account_type not in {"admin", "customer"}:
        abort(404)

    if request.method == "POST":
        validate_csrf()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if password_error := password_strength_error(password):
            flash(password_error, "error")
        elif password != confirm_password:
            flash("Password confirmation does not match.", "error")
        else:
            try:
                with get_db() as database:
                    if account_type == "admin":
                        username = request.form.get("username", "").strip()
                        full_name = request.form.get("full_name", "").strip()
                        email = request.form.get("email", "").strip().lower() or None
                        role = request.form.get("role", "admin")
                        if len(username) < 3:
                            raise ValueError("Username must contain at least 3 characters.")
                        if role not in {"admin", "admin_marketing", "admin_technical", "superadmin"}:
                            raise ValueError("Select a valid administrator role.")
                        if email and ("@" not in email or len(email) > 254):
                            raise ValueError("Enter a valid administrator email address.")
                        avatar_url = save_account_photo(request.files.get("avatar"))
                        cursor = database.execute(
                            """INSERT INTO admins
                               (username, full_name, email, avatar_url, password_hash, role)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (username, full_name, email, avatar_url,
                             generate_password_hash(password), role),
                        )
                        account_label = username
                    else:
                        full_name = request.form.get("full_name", "").strip()
                        email = request.form.get("email", "").strip().lower()
                        if len(full_name) < 2:
                            raise ValueError("Enter the customer's full name.")
                        if "@" not in email or len(email) > 254:
                            raise ValueError("Enter a valid customer email address.")
                        avatar_url = save_account_photo(request.files.get("avatar"))
                        cursor = database.execute(
                            """INSERT INTO customers
                               (full_name, email, avatar_url, password_hash)
                               VALUES (?, ?, ?, ?)""",
                            (full_name, email, avatar_url,
                             generate_password_hash(password)),
                        )
                        account_label = email
                log_activity(
                    "admin",
                    session["admin_id"],
                    session["admin_username"],
                    f"{account_type}_account_create",
                    f"{account_label} (ID #{cursor.lastrowid})",
                )
                flash(f"{account_type.title()} account created successfully.", "success")
                return redirect(url_for("admin_accounts"))
            except ValueError as error:
                flash(str(error), "error")
            except DB_INTEGRITY_ERRORS:
                flash(
                    "That username or email address is already in use.", "error"
                )

    return render_template(
        "admin_managed_account_form.html",
        account_type=account_type,
        account=None,
        mode="create",
    )


@app.route(
    "/admin/accounts/<account_type>/<int:account_id>/edit",
    methods=["GET", "POST"],
)
@superadmin_required
def admin_account_edit(account_type, account_id):
    if account_type not in {"admin", "customer"}:
        abort(404)
    table = "admins" if account_type == "admin" else "customers"
    with get_db() as database:
        row = database.execute(
            f"SELECT * FROM {table} WHERE id = ?", (account_id,)
        ).fetchone()
    if not row:
        flash(
            "That account is no longer available. Refresh the directory and try again.",
            "error",
        )
        return redirect(url_for("admin_accounts"))
    account = dict(row)

    if request.method == "POST":
        validate_csrf()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if password and (password_error := password_strength_error(password)):
            flash(password_error, "error")
        elif password != confirm_password:
            flash("Password confirmation does not match.", "error")
        else:
            try:
                with get_db() as database:
                    if account_type == "admin":
                        username = request.form.get("username", "").strip()
                        full_name = request.form.get("full_name", "").strip()
                        email = request.form.get("email", "").strip().lower() or None
                        role = request.form.get("role", "admin")
                        if len(username) < 3:
                            raise ValueError("Username must contain at least 3 characters.")
                        if role not in {"admin", "admin_marketing", "admin_technical", "superadmin"}:
                            raise ValueError("Select a valid administrator role.")
                        if email and ("@" not in email or len(email) > 254):
                            raise ValueError("Enter a valid administrator email address.")
                        if account_id == session["admin_id"] and role != "superadmin":
                            raise ValueError(
                                "You cannot remove superadmin access from your active account."
                            )
                        fields = ["username = ?", "full_name = ?", "email = ?", "role = ?"]
                        values = [username, full_name, email, role]
                        account_label = username
                    else:
                        full_name = request.form.get("full_name", "").strip()
                        email = request.form.get("email", "").strip().lower()
                        if len(full_name) < 2:
                            raise ValueError("Enter the customer's full name.")
                        if "@" not in email or len(email) > 254:
                            raise ValueError("Enter a valid customer email address.")
                        fields = ["full_name = ?", "email = ?"]
                        values = [full_name, email]
                        account_label = email
                    if request.form.get("remove_avatar") == "1":
                        fields.append("avatar_url = NULL")
                    else:
                        avatar_url = save_account_photo(request.files.get("avatar"))
                        if avatar_url:
                            fields.append("avatar_url = ?")
                            values.append(avatar_url)
                    if password:
                        fields.append("password_hash = ?")
                        values.append(generate_password_hash(password))
                    values.append(account_id)
                    database.execute(
                        f"UPDATE {table} SET {', '.join(fields)} WHERE id = ?",
                        values,
                    )
                if account_type == "admin" and account_id == session["admin_id"]:
                    session["admin_username"] = username
                    session["admin_role"] = role
                log_activity(
                    "admin",
                    session["admin_id"],
                    session["admin_username"],
                    f"{account_type}_account_update",
                    f"{account_label} (ID #{account_id})"
                    + (", password reset" if password else ""),
                )
                flash(f"{account_type.title()} account updated successfully.", "success")
                return redirect(url_for("admin_accounts"))
            except ValueError as error:
                flash(str(error), "error")
            except DB_INTEGRITY_ERRORS:
                flash(
                    "That username or email address is already in use.", "error"
                )

    return render_template(
        "admin_managed_account_form.html",
        account_type=account_type,
        account=account,
        mode="edit",
    )


@app.route("/admin")
@login_required
def admin_dashboard():
    query = request.args.get("q", "").strip()
    with get_db() as database:
        if query:
            catalog = rows_to_dicts(
                database.execute(
                    "SELECT * FROM products WHERE name LIKE ? OR brand LIKE ? ORDER BY updated_at DESC",
                    (f"%{query}%", f"%{query}%"),
                )
            )
        else:
            catalog = rows_to_dicts(
                database.execute("SELECT * FROM products ORDER BY updated_at DESC")
            )
    return render_template("admin_dashboard.html", products=catalog, query=query)


@app.route("/admin/activity")
@superadmin_required
def admin_activity():
    with get_db() as database:
        logs = rows_to_dicts(
            database.execute(
                """SELECT log.*, admin.role AS actor_role
                   FROM activity_logs log
                   LEFT JOIN admins admin
                     ON log.actor_type = 'admin' AND admin.id = log.actor_id
                   ORDER BY log.id DESC LIMIT 500"""
            )
        )
    log_groups = {"superadmin": [], "admin": [], "customer": []}
    for log in logs:
        if log["actor_type"] == "customer":
            group = "customer"
        elif log["actor_type"] == "admin" and log.get("actor_role") == "superadmin":
            group = "superadmin"
        else:
            group = "admin"
        log_groups[group].append(log)
    return render_template("admin_activity.html", log_groups=log_groups)


@app.route("/admin/review-requests")
@login_required
def admin_review_requests():
    with get_db() as database:
        if session.get("admin_role") == "admin_marketing":
            database.execute(
                """UPDATE review_requests
                   SET assigned_marketing_admin_id = ?,
                       assigned_marketing_at = CURRENT_TIMESTAMP,
                       status = 'marketing_review'
                   WHERE assigned_marketing_admin_id IS NULL
                     AND status IN ('submitted', 'pending')""",
                (session["admin_id"],),
            )
        requests_list = rows_to_dicts(
            database.execute(
                """SELECT r.*, o.name AS ai_option_name,
                          c.requirements_summary AS ai_requirements_summary,
                          owner.username AS marketing_owner_username,
                          COALESCE(NULLIF(owner.full_name, ''), owner.username) AS marketing_owner_name,
                          COUNT(i.id) AS line_count,
                          COALESCE(SUM(i.quantity), 0) AS item_count,
                          SUM(CASE WHEN i.unit_price IS NOT NULL
                                   THEN i.unit_price * i.quantity END) AS total_price,
                          SUM(CASE WHEN i.unit_price IS NULL THEN 1 ELSE 0 END) AS unpriced_count
                   FROM review_requests r
                   LEFT JOIN review_request_items i ON i.request_id = r.id
                   LEFT JOIN ai_solution_options o ON o.id = r.ai_solution_option_id
                   LEFT JOIN ai_conversations c ON c.id = o.conversation_id
                   LEFT JOIN admins owner ON owner.id = r.assigned_marketing_admin_id
                   GROUP BY r.id, o.name, c.requirements_summary,
                            owner.username, owner.full_name
                   ORDER BY r.id DESC"""
            )
        )
        items = rows_to_dicts(
            database.execute(
                "SELECT * FROM review_request_items ORDER BY request_id DESC, id"
            )
        )
        selected_options = rows_to_dicts(
            database.execute(
                """SELECT link.request_id, option.id, option.option_key, option.name
                   FROM review_request_solution_options link
                   JOIN ai_solution_options option ON option.id = link.option_id
                   ORDER BY link.request_id DESC, option.id"""
            )
        )
        messages = rows_to_dicts(
            database.execute(
                "SELECT * FROM review_request_messages ORDER BY request_id DESC, id"
            )
        )
        materials = rows_to_dicts(
            database.execute(
                "SELECT * FROM review_request_materials ORDER BY request_id DESC, id"
            )
        )
    if session.get("admin_role") == "admin_technical":
        requests_list = [
            review for review in requests_list
            if review["status"] in {"technical_review", "site_survey_scheduled", "marketing_bom_review"}
        ]
    elif session.get("admin_role") in {"admin", "admin_marketing"}:
        requests_list = [
            review for review in requests_list
            if review["status"] not in {"technical_review", "site_survey_scheduled"}
            and (
                session.get("admin_role") == "admin"
                or review.get("assigned_marketing_admin_id") == session.get("admin_id")
            )
        ]
    items_by_request = {}
    for item in items:
        items_by_request.setdefault(item["request_id"], []).append(item)
    options_by_request = {}
    for option in selected_options:
        options_by_request.setdefault(option["request_id"], []).append(option)
    messages_by_request = {}
    for message in messages:
        messages_by_request.setdefault(message["request_id"], []).append(message)
    materials_by_request = {}
    for material in materials:
        materials_by_request.setdefault(material["request_id"], []).append(material)
    return render_template(
        "admin_review_requests.html",
        requests=requests_list,
        items_by_request=items_by_request,
        options_by_request=options_by_request,
        messages_by_request=messages_by_request,
        materials_by_request=materials_by_request,
    )


@app.route("/admin/messages")
@login_required
def admin_messages():
    role = session.get("admin_role")
    access_sql = "1 = 1"
    access_params = []
    if role == "admin_marketing":
        access_sql = "r.assigned_marketing_admin_id = ?"
        access_params = [session["admin_id"]]
    elif role == "admin_technical":
        access_sql = "r.status IN ('technical_review', 'site_survey_scheduled', 'marketing_bom_review')"
    elif role == "admin":
        access_sql = "r.status NOT IN ('technical_review', 'site_survey_scheduled')"

    show_archived = request.args.get("view") == "archived"
    with get_db() as database:
        conversations = rows_to_dicts(
            database.execute(
                f"""SELECT r.id, r.customer_id, r.customer_name, r.customer_email,
                           r.status, r.created_at, r.service_scope,
                           CASE WHEN COALESCE(pref.is_muted, 0) = 1
                                  AND (pref.muted_until IS NULL OR pref.muted_until > CURRENT_TIMESTAMP)
                                THEN 1 ELSE 0 END AS is_muted,
                           pref.muted_until,
                           COALESCE(pref.is_archived, 0) AS is_archived,
                           COALESCE(pref.is_blocked, 0) AS is_blocked,
                           COUNT(DISTINCT item.id) AS product_count,
                           MAX(message.id) AS latest_message_id,
                           MAX(message.created_at) AS latest_message_at,
                           (SELECT latest.message FROM review_request_messages latest
                            WHERE latest.request_id = r.id
                            ORDER BY latest.id DESC LIMIT 1) AS latest_message,
                           (SELECT COUNT(*) FROM review_request_messages incoming
                            WHERE incoming.request_id = r.id
                              AND incoming.sender_type = 'customer'
                              AND NOT EXISTS (
                                SELECT 1 FROM review_message_reads receipt
                                WHERE receipt.message_id = incoming.id
                                  AND receipt.reader_type = 'admin'
                                  AND receipt.reader_id = ?
                              )) AS unread_count
                    FROM review_requests r
                    LEFT JOIN review_request_items item ON item.request_id = r.id
                    LEFT JOIN review_request_messages message ON message.request_id = r.id
                    LEFT JOIN admin_conversation_preferences pref
                      ON pref.request_id = r.id AND pref.admin_id = ?
                    WHERE {access_sql}
                      AND pref.deleted_at IS NULL
                      AND COALESCE(pref.is_archived, 0) = ?
                    GROUP BY r.id, pref.is_muted, pref.muted_until,
                             pref.is_archived, pref.is_blocked
                    ORDER BY COALESCE(MAX(message.id), 0) DESC, r.id DESC""",
                (
                    session["admin_id"],
                    session["admin_id"],
                    *access_params,
                    1 if show_archived else 0,
                ),
            )
        )
        requested_id = request.args.get("request_id", type=int)
        active = next((row for row in conversations if row["id"] == requested_id), None)
        if active is None and conversations:
            active = conversations[0]
        active_messages = []
        active_items = []
        customer_profile = None
        if active:
            active_messages = rows_to_dicts(
                database.execute(
                    """SELECT * FROM review_request_messages
                       WHERE request_id = ? ORDER BY id""",
                    (active["id"],),
                )
            )
            active_items = rows_to_dicts(
                database.execute(
                    """SELECT product_name, brand, quantity FROM review_request_items
                       WHERE request_id = ? ORDER BY id""",
                    (active["id"],),
                )
            )
            customer_profile = database.execute(
                """SELECT customer.id, customer.full_name, customer.email,
                          customer.avatar_url, customer.created_at,
                          customer.last_login_at, customer.status,
                          (SELECT COUNT(*) FROM review_requests review
                           WHERE review.customer_id = customer.id) AS request_count,
                          (SELECT COUNT(*) FROM review_requests review
                           WHERE review.customer_id = customer.id
                             AND review.status = 'approved') AS approved_count,
                          (SELECT COUNT(*) FROM review_requests review
                           WHERE review.customer_id = customer.id
                             AND review.status NOT IN ('approved', 'cancelled')) AS active_count
                   FROM customers customer WHERE customer.id = ?""",
                (active["customer_id"],),
            ).fetchone()
            database.execute(
                """INSERT OR IGNORE INTO review_message_reads
                   (message_id, reader_type, reader_id)
                   SELECT id, 'admin', ? FROM review_request_messages
                   WHERE request_id = ?""",
                (session["admin_id"], active["id"]),
            )
            active["unread_count"] = 0
    return render_template(
        "admin_messages.html",
        conversations=conversations,
        active=active,
        active_messages=active_messages,
        active_items=active_items,
        customer_profile=dict(customer_profile) if customer_profile else None,
        show_archived=show_archived,
    )


@app.route("/admin/messages/<int:request_id>/action", methods=["POST"])
@login_required
def admin_message_action(request_id):
    validate_csrf()
    action = request.form.get("action", "")
    if action not in {"mute", "unmute", "archive", "unarchive", "block", "unblock", "delete"}:
        abort(400)
    with get_db() as database:
        review = database.execute(
            "SELECT id, assigned_marketing_admin_id, status FROM review_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if not review:
            abort(404)
        role = session.get("admin_role")
        if role == "admin_marketing" and review["assigned_marketing_admin_id"] != session["admin_id"]:
            abort(403)
        if role == "admin_technical" and review["status"] not in {
            "technical_review", "site_survey_scheduled", "marketing_bom_review"
        }:
            abort(403)
        database.execute(
            """INSERT OR IGNORE INTO admin_conversation_preferences
               (admin_id, request_id) VALUES (?, ?)""",
            (session["admin_id"], request_id),
        )
        updates = {
            "archive": ("is_archived", 1), "unarchive": ("is_archived", 0),
            "block": ("is_blocked", 1), "unblock": ("is_blocked", 0),
        }
        if action == "delete":
            database.execute(
                """UPDATE admin_conversation_preferences
                   SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE admin_id = ? AND request_id = ?""",
                (session["admin_id"], request_id),
            )
        elif action == "mute":
            duration = request.form.get("duration", "forever")
            duration_minutes = {"15m": 15, "1h": 60, "8h": 480, "24h": 1440}
            if duration not in {*duration_minutes, "forever"}:
                abort(400)
            muted_until = None
            if duration != "forever":
                muted_until = (
                    datetime.now(timezone.utc) + timedelta(minutes=duration_minutes[duration])
                ).strftime("%Y-%m-%d %H:%M:%S")
            database.execute(
                """UPDATE admin_conversation_preferences
                   SET is_muted = 1, muted_until = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE admin_id = ? AND request_id = ?""",
                (muted_until, session["admin_id"], request_id),
            )
        elif action == "unmute":
            database.execute(
                """UPDATE admin_conversation_preferences
                   SET is_muted = 0, muted_until = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE admin_id = ? AND request_id = ?""",
                (session["admin_id"], request_id),
            )
        else:
            column, value = updates[action]
            database.execute(
                f"""UPDATE admin_conversation_preferences
                    SET {column} = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE admin_id = ? AND request_id = ?""",
                (value, session["admin_id"], request_id),
            )
    action_messages = {
        "mute": "Conversation muted.", "unmute": "Conversation unmuted.",
        "archive": "Conversation archived.", "unarchive": "Conversation restored.",
        "block": "Customer blocked for this request.", "unblock": "Customer unblocked.",
        "delete": "Conversation removed from your inbox.",
    }
    flash(action_messages[action], "success")
    destination = "/admin/messages?view=archived" if action == "unarchive" else "/admin/messages"
    return redirect(destination)


@app.route("/admin/review-requests/<int:request_id>/delete", methods=["POST"])
@login_required
def delete_review_request(request_id):
    validate_csrf()
    if session.get("admin_role") != "superadmin":
        abort(403)
    with get_db() as database:
        review = database.execute(
            "SELECT id, customer_name FROM review_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if not review:
            abort(404)
        database.execute(
            """DELETE FROM review_message_reads
               WHERE message_id IN (
                 SELECT id FROM review_request_messages WHERE request_id = ?
               )""",
            (request_id,),
        )
        for table in (
            "admin_conversation_preferences",
            "calendar_events",
            "review_request_materials",
            "review_request_solution_options",
            "review_request_items",
            "review_request_messages",
        ):
            database.execute(f"DELETE FROM {table} WHERE request_id = ?", (request_id,))
        database.execute("DELETE FROM review_requests WHERE id = ?", (request_id,))
    log_activity(
        "admin", session["admin_id"], session["admin_username"],
        "review_request_deleted", f"Request #{request_id}: {review['customer_name']}"
    )
    flash(f"Review request #{request_id:05d} was permanently deleted.", "success")
    return redirect(url_for("admin_review_requests"))


def build_review_documents(review, items, materials=None):
    materials = materials or []
    bom_stream = io.StringIO()
    writer = csv.writer(bom_stream)
    writer.writerow(["VTIC BOM", f"Request #{review['id']:05d}"])
    writer.writerow(["Manufacturer", "Product", "SKU", "Quantity", "Unit Price", "Line Total"])
    total = 0.0
    for item in items:
        unit_price = item["unit_price"] or 0
        line_total = unit_price * item["quantity"]
        total += line_total
        writer.writerow(
            [item["brand"], item["product_name"], f"VT-{item['product_id']:04d}", item["quantity"], f"{unit_price:.2f}", f"{line_total:.2f}"]
        )
    writer.writerow([])
    if materials:
        writer.writerow(["INSTALLATION MATERIALS"])
        writer.writerow(["Material", "Quantity", "Unit", "Notes"])
        for material in materials:
            writer.writerow(
                [material["material_name"], material["quantity"], material["unit"], material["notes"]]
            )
        writer.writerow([])
    writer.writerow(["TOTAL", "", "", "", "", f"{total:.2f}"])
    proposal = (
        f"VTIC COMMERCIAL PROPOSAL\nRequest #{review['id']:05d}\n\n"
        f"Prepared for: {review['customer_name']} <{review['customer_email']}>\n"
        f"Project notes: {review['notes'] or 'None provided'}\n\n"
        f"Scope: Supply of {sum(item['quantity'] for item in items)} item(s) across "
        f"{len(items)} product line(s).\n"
        f"Service scope: {review.get('service_scope') or 'Product supply'}\n"
        f"Installation materials: {len(materials)} line(s).\n"
        f"Commercial total: PHP {total:,.2f}\n\n"
        "All specifications, availability, delivery schedules and final commercial terms "
        "remain subject to VTIC confirmation."
    )
    return bom_stream.getvalue(), proposal


def send_review_approved_email(review):
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", username).strip()
    if not host or not sender:
        return False
    message = EmailMessage()
    message["Subject"] = f"VTIC products reviewed — Request #{review['id']:05d}"
    message["From"] = sender
    message["To"] = review["customer_email"]
    message.set_content(
        f"Hello {review['customer_name']},\n\n"
        "Your selected products have been reviewed and approved by VTIC. "
        "Our team is preparing the approved BOM, pricing and proposal for release. "
        "We will send the complete documents shortly.\n\n"
        f"Reference: VTIC request #{review['id']:05d}\n\nVTIC Solutions Team"
    )
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"
    server_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with server_class(host, port, timeout=20) as server:
        if not use_ssl:
            server.starttls()
        if username:
            server.login(username, password)
        server.send_message(message)
    return True


def send_customer_workflow_email(review, subject, body):
    host = os.environ.get("SMTP_HOST", "").strip()
    username = os.environ.get("SMTP_USERNAME", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", username).strip()
    if not host or not sender:
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = review["customer_email"]
    message.set_content(
        f"Hello {review['customer_name']},\n\n{body}\n\n"
        f"Reference: VTIC request #{review['id']:05d}\n\nVTIC Solutions Team"
    )
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"
    server_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with server_class(host, port, timeout=20) as server:
        if not use_ssl:
            server.starttls()
        if username:
            server.login(username, password)
        server.send_message(message)
    return True


def add_review_message(database, request_id, sender_type, sender_id, sender_name, message):
    database.execute(
        """INSERT INTO review_request_messages
           (request_id, sender_type, sender_id, sender_name, message,
            read_by_customer, read_by_admin)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            request_id,
            sender_type,
            sender_id,
            sender_name,
            message[:3000],
            1 if sender_type == "customer" else 0,
            1 if sender_type == "admin" else 0,
        ),
    )


def review_notification_scope():
    if session.get("customer_id"):
        return (
            "review.customer_id = ? AND message.sender_type = 'admin'",
            (session["customer_id"],),
            "customer",
            session["customer_id"],
            url_for("customer_reviews"),
        )
    role = session.get("admin_role")
    if role == "admin_marketing":
        condition = "review.assigned_marketing_admin_id = ? AND message.sender_type = 'customer'"
        parameters = (session["admin_id"],)
    elif role == "admin_technical":
        condition = "review.status IN ('technical_review', 'site_survey_scheduled', 'marketing_bom_review') AND message.sender_type = 'customer'"
        parameters = ()
    else:
        condition = "message.sender_type = 'customer'"
        parameters = ()
    condition += """ AND NOT EXISTS (
        SELECT 1 FROM admin_conversation_preferences muted
        WHERE muted.request_id = review.id AND muted.admin_id = ?
          AND muted.is_muted = 1
          AND (muted.muted_until IS NULL OR muted.muted_until > CURRENT_TIMESTAMP)
    )"""
    parameters = (*parameters, session["admin_id"])
    return condition, parameters, "admin", session["admin_id"], url_for("admin_messages")


@app.route("/api/message-notifications")
@customer_required
def message_notifications():
    condition, parameters, reader_type, reader_id, target_url = review_notification_scope()
    with get_db() as database:
        unread = database.execute(
            f"""SELECT COUNT(*) AS unread_count, MAX(message.id) AS latest_id
                FROM review_request_messages message
                JOIN review_requests review ON review.id = message.request_id
                WHERE {condition}
                  AND NOT EXISTS (
                    SELECT 1 FROM review_message_reads receipt
                    WHERE receipt.message_id = message.id
                      AND receipt.reader_type = ? AND receipt.reader_id = ?
                  )""",
            (*parameters, reader_type, reader_id),
        ).fetchone()
        latest = database.execute(
            f"""SELECT message.id, message.sender_name, message.message,
                       message.request_id, message.created_at
                FROM review_request_messages message
                JOIN review_requests review ON review.id = message.request_id
                WHERE {condition} ORDER BY message.id DESC LIMIT 1""",
            parameters,
        ).fetchone()
    return jsonify(
        unread_count=unread["unread_count"],
        latest_id=unread["latest_id"],
        latest=dict(latest) if latest else None,
        target_url=target_url,
    )


@app.route("/api/live-state")
@customer_required
def live_state():
    if session.get("customer_id"):
        access_sql = "review.customer_id = ?"
        parameters = (session["customer_id"],)
    else:
        role = session.get("admin_role")
        if role == "admin_marketing":
            access_sql = "review.assigned_marketing_admin_id = ?"
            parameters = (session["admin_id"],)
        elif role == "admin_technical":
            access_sql = "review.status IN ('technical_review', 'site_survey_scheduled', 'marketing_bom_review')"
            parameters = ()
        elif role == "admin":
            access_sql = "review.status NOT IN ('technical_review', 'site_survey_scheduled')"
            parameters = ()
        else:
            access_sql = "1 = 1"
            parameters = ()
    with get_db() as database:
        review_state = database.execute(
            f"""SELECT COUNT(*) AS total, COALESCE(MAX(review.id), 0) AS latest_id,
                       COALESCE(GROUP_CONCAT(
                         review.id || ':' || review.status || ':' ||
                         COALESCE(review.service_scope, '') || ':' ||
                         COALESCE(review.site_survey_at, '')
                       ), '') AS workflow_state
                FROM review_requests review WHERE {access_sql}""",
            parameters,
        ).fetchone()
        message_state = database.execute(
            f"""SELECT COUNT(*) AS total, COALESCE(MAX(message.id), 0) AS latest_id
                FROM review_request_messages message
                JOIN review_requests review ON review.id = message.request_id
                WHERE {access_sql}""",
            parameters,
        ).fetchone()
        calendar_state = database.execute(
            f"""SELECT COUNT(*) AS total, COALESCE(MAX(event.id), 0) AS latest_id,
                       COALESCE(MAX(event.created_at), '') AS latest_at
                FROM calendar_events event
                LEFT JOIN review_requests review ON review.id = event.request_id
                WHERE event.request_id IS NULL OR {access_sql}""",
            parameters,
        ).fetchone()
    return jsonify(
        reviews=dict(review_state),
        messages=dict(message_state),
        calendar=dict(calendar_state),
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@app.route("/api/message-notifications/read", methods=["POST"])
@customer_required
def read_message_notifications():
    if not secrets.compare_digest(
        session.get("csrf_token", ""), request.headers.get("X-CSRF-Token", "")
    ):
        abort(400, "Invalid security token")
    condition, parameters, reader_type, reader_id, _ = review_notification_scope()
    with get_db() as database:
        database.execute(
            f"""INSERT OR IGNORE INTO review_message_reads
                (message_id, reader_type, reader_id)
                SELECT message.id, ?, ? FROM review_request_messages message
                JOIN review_requests review ON review.id = message.request_id
                WHERE {condition}""",
            (reader_type, reader_id, *parameters),
        )
    return jsonify(ok=True)


@app.route("/admin/review-requests/<int:request_id>/message", methods=["POST"])
@login_required
def admin_review_message(request_id):
    validate_csrf()
    message = request.form.get("message", "").strip()
    if not message:
        flash("Write a message before sending it.", "error")
        return redirect(f"{url_for('admin_review_requests')}#request-{request_id}")
    if len(message) > 3000:
        flash("Messages must be 3,000 characters or fewer.", "error")
        return redirect(f"{url_for('admin_review_requests')}#request-{request_id}")
    with get_db() as database:
        review = database.execute(
            "SELECT * FROM review_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if not review:
            abort(404)
        if (
            session.get("admin_role") == "admin_marketing"
            and review["assigned_marketing_admin_id"] != session["admin_id"]
        ):
            abort(403)
        add_review_message(
            database,
            request_id,
            "admin",
            session["admin_id"],
            session["admin_username"],
            message,
        )
    emailed = False
    if request.form.get("notify_email") == "1":
        try:
            emailed = send_customer_workflow_email(
                dict(review),
                f"New VTIC message — Request #{request_id:05d}",
                message,
            )
        except Exception:
            app.logger.exception("Request chat email failed")
    log_activity(
        "admin",
        session["admin_id"],
        session["admin_username"],
        "review_chat_message",
        f"Request #{request_id}",
    )
    flash("Message sent in customer conversation." + (" Email sent." if emailed else ""), "success")
    return_to = request.form.get("return_to", "")
    if return_to.startswith("/admin/messages"):
        return redirect(return_to)
    return redirect(f"{url_for('admin_review_requests')}#request-{request_id}")


@app.route("/account/reviews/<int:request_id>/message", methods=["POST"])
@customer_required
def customer_review_message(request_id):
    validate_csrf()
    message = request.form.get("message", "").strip()
    if not message:
        flash("Write a message before sending it.", "error")
        return redirect(f"{url_for('customer_reviews')}#request-{request_id}")
    if len(message) > 3000:
        flash("Messages must be 3,000 characters or fewer.", "error")
        return redirect(f"{url_for('customer_reviews')}#request-{request_id}")
    with get_db() as database:
        review = database.execute(
            """SELECT id FROM review_requests
               WHERE id = ? AND customer_id = ?
                 AND NOT EXISTS (
                   SELECT 1 FROM admin_conversation_preferences preference
                   WHERE preference.request_id = review_requests.id
                     AND preference.is_blocked = 1
                 )""",
            (request_id, session["customer_id"]),
        ).fetchone()
        if not review:
            flash("Messaging is unavailable for this request. Contact VTIC through the project desk.", "error")
            return redirect(f"{url_for('customer_reviews')}#request-{request_id}")
        add_review_message(
            database,
            request_id,
            "customer",
            session["customer_id"],
            session.get("customer_name", "Customer"),
            message,
        )
    log_activity(
        "customer",
        session["customer_id"],
        session.get("customer_email", "customer"),
        "review_chat_message",
        f"Request #{request_id}",
    )
    flash("Your message was sent to the VTIC team.", "success")
    return redirect(f"{url_for('customer_reviews')}#request-{request_id}")


def require_review_role(*roles):
    if session.get("admin_role") not in {*roles, "superadmin"}:
        abort(403)


@app.route("/admin/review-requests/<int:request_id>/prepare", methods=["POST"])
@login_required
def admin_review_prepare(request_id):
    validate_csrf()
    require_review_role("admin", "admin_marketing")
    with get_db() as database:
        review = database.execute("SELECT * FROM review_requests WHERE id = ?", (request_id,)).fetchone()
        if not review:
            abort(404)
        if session.get("admin_role") == "admin_marketing" and review["assigned_marketing_admin_id"] not in {None, session["admin_id"]}:
            abort(403)
        if review["status"] not in {"submitted", "pending", "marketing_review"}:
            flash("This request has already completed its initial Marketing review.", "error")
            return redirect(url_for("admin_review_requests"))
        items = rows_to_dicts(database.execute("SELECT * FROM review_request_items WHERE request_id = ? ORDER BY id", (request_id,)))
        for item in items:
            value = request.form.get(f"price_{item['id']}", "").replace(",", "").replace("₱", "").strip()
            try:
                price = float(value)
            except ValueError:
                flash(f"Enter a valid price for {item['product_name']}.", "error")
                return redirect(url_for("admin_review_requests"))
            if price < 0:
                flash("Prices cannot be negative.", "error")
                return redirect(url_for("admin_review_requests"))
            item["unit_price"] = price
            database.execute("UPDATE review_request_items SET unit_price = ? WHERE id = ?", (price, item["id"]))
        message = (
            "VTIC Marketing has reviewed the initial product pricing. "
            "Would you like a product-only quotation, or a complete setup quotation "
            "including structured cabling and installation workers?"
        )
        database.execute(
            """UPDATE review_requests SET status = 'awaiting_customer_scope',
               commercial_notes = ?, marketing_reviewed_by = ?,
               assigned_marketing_admin_id = COALESCE(assigned_marketing_admin_id, ?),
               assigned_marketing_at = COALESCE(assigned_marketing_at, CURRENT_TIMESTAMP),
               marketing_reviewed_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (request.form.get("commercial_notes", "").strip()[:4000], session["admin_id"], session["admin_id"], request_id),
        )
        add_review_message(database, request_id, "admin", session["admin_id"], session["admin_username"], message)
    emailed = False
    if request.form.get("notify_email") == "1":
        try:
            emailed = send_customer_workflow_email(dict(review), f"Choose your VTIC quotation scope — Request #{request_id:05d}", message)
        except Exception:
            app.logger.exception("Customer scope email failed")
    log_activity("admin", session["admin_id"], session["admin_username"], "marketing_initial_review", f"Request #{request_id}")
    flash("Pricing saved and the scope question was sent in customer web chat." + (" Email sent." if emailed else ""), "success")
    return redirect(url_for("admin_review_requests"))


@app.route("/account/reviews/<int:request_id>/scope", methods=["POST"])
@customer_required
def customer_review_scope(request_id):
    validate_csrf()
    if not session.get("customer_id"):
        abort(403)
    service_scope = request.form.get("service_scope", "")
    if service_scope not in {"product_only", "full_setup"}:
        abort(400)
    with get_db() as database:
        review = database.execute(
            "SELECT * FROM review_requests WHERE id = ? AND customer_id = ?",
            (request_id, session["customer_id"]),
        ).fetchone()
        if not review or review["status"] != "awaiting_customer_scope":
            flash("This request is not waiting for a scope decision.", "error")
            return redirect(url_for("customer_reviews"))
        label = "product supply only" if service_scope == "product_only" else "complete setup with structured cabling and installation"
        database.execute(
            """UPDATE review_requests SET service_scope = ?,
               status = 'marketing_final_pricing', customer_scope_decided_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (service_scope, request_id),
        )
        add_review_message(database, request_id, "customer", session["customer_id"], session.get("customer_name", "Customer"), f"I confirm that I want {label}.")
    log_activity("customer", session["customer_id"], session.get("customer_email", "customer"), "review_scope_selected", f"Request #{request_id}: {service_scope}")
    flash("Your project scope was sent to VTIC Marketing.", "success")
    return redirect(url_for("customer_reviews"))


@app.route("/admin/review-requests/<int:request_id>/marketing-final", methods=["POST"])
@login_required
def marketing_final_pricing(request_id):
    validate_csrf()
    require_review_role("admin", "admin_marketing")
    with get_db() as database:
        review = database.execute("SELECT * FROM review_requests WHERE id = ?", (request_id,)).fetchone()
        if review and session.get("admin_role") == "admin_marketing" and review["assigned_marketing_admin_id"] != session["admin_id"]:
            abort(403)
        if not review or review["status"] != "marketing_final_pricing":
            flash("This request is not ready for final pricing.", "error")
            return redirect(url_for("admin_review_requests"))
        items = rows_to_dicts(database.execute("SELECT * FROM review_request_items WHERE request_id = ? ORDER BY id", (request_id,)))
        for item in items:
            value = request.form.get(f"price_{item['id']}", "").replace(",", "").replace("₱", "").strip()
            try:
                price = float(value)
            except ValueError:
                flash(f"Enter a valid price for {item['product_name']}.", "error")
                return redirect(url_for("admin_review_requests"))
            if price < 0:
                flash("Prices cannot be negative.", "error")
                return redirect(url_for("admin_review_requests"))
            database.execute("UPDATE review_request_items SET unit_price = ? WHERE id = ?", (price, item["id"]))
            item["unit_price"] = price
        if review["service_scope"] == "product_only":
            bom, proposal = build_review_documents(dict(review), items)
            next_status = "superadmin_review"
            database.execute("UPDATE review_requests SET status = ?, bom_document = ?, proposal_document = ?, marketing_reviewed_by = ?, marketing_reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (next_status, bom, proposal, session["admin_id"], request_id))
        else:
            next_status = "technical_review"
            database.execute("UPDATE review_requests SET status = ?, marketing_reviewed_by = ?, marketing_reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (next_status, session["admin_id"], request_id))
        add_review_message(database, request_id, "admin", session["admin_id"], session["admin_username"], "Final product pricing is complete." + (" The request is now with Technical for survey and BOM validation." if next_status == "technical_review" else " The product-only proposal is now awaiting final approval."))
    flash("Final pricing completed and the request was routed to " + ("Technical." if next_status == "technical_review" else "Superadmin."), "success")
    return redirect(url_for("admin_review_requests"))


@app.route("/admin/review-requests/<int:request_id>/schedule-survey", methods=["POST"])
@login_required
def technical_schedule_survey(request_id):
    validate_csrf()
    require_review_role("admin_technical")
    starts_at = request.form.get("starts_at", "").strip()
    location = request.form.get("location", "").strip()
    notes = request.form.get("survey_notes", "").strip()
    try:
        datetime.fromisoformat(starts_at)
    except ValueError:
        flash("Choose a valid site-survey date and time.", "error")
        return redirect(url_for("admin_review_requests"))
    with get_db() as database:
        review = database.execute("SELECT * FROM review_requests WHERE id = ?", (request_id,)).fetchone()
        if not review or review["status"] not in {"technical_review", "site_survey_scheduled"}:
            flash("This request is not ready for site-survey scheduling.", "error")
            return redirect(url_for("admin_review_requests"))
        database.execute("UPDATE review_requests SET status = 'site_survey_scheduled', site_survey_at = ?, site_survey_location = ?, site_survey_notes = ? WHERE id = ?", (starts_at, location, notes, request_id))
        database.execute("DELETE FROM calendar_events WHERE request_id = ? AND event_type = 'site_survey'", (request_id,))
        database.execute("""INSERT INTO calendar_events (request_id, event_type, title, customer_name, customer_email, starts_at, location, notes, created_by) VALUES (?, 'site_survey', ?, ?, ?, ?, ?, ?, ?)""", (request_id, f"Site survey — Request #{request_id:05d}", review["customer_name"], review["customer_email"], starts_at, location, notes, session["admin_id"]))
        message = f"Your VTIC site survey is scheduled for {starts_at.replace('T', ' ')} at {location or 'the agreed project site'}."
        add_review_message(database, request_id, "admin", session["admin_id"], session["admin_username"], message)
    emailed = False
    if request.form.get("notify_email") == "1":
        try:
            emailed = send_customer_workflow_email(dict(review), f"VTIC site survey scheduled — Request #{request_id:05d}", message)
        except Exception:
            app.logger.exception("Site survey email failed")
    flash("Site survey added to the calendar and customer web chat." + (" Email sent." if emailed else ""), "success")
    return redirect(url_for("admin_calendar"))


@app.route("/admin/review-requests/<int:request_id>/technical-complete", methods=["POST"])
@login_required
def technical_review_complete(request_id):
    validate_csrf()
    require_review_role("admin_technical")
    material_lines = request.form.get("materials", "").splitlines()
    parsed_materials = []
    for line in material_lines:
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        name = parts[0]
        try:
            quantity = float(parts[1]) if len(parts) > 1 and parts[1] else 1
        except ValueError:
            flash(f"Invalid material quantity in: {line}", "error")
            return redirect(url_for("admin_review_requests"))
        if quantity <= 0:
            flash(f"Material quantities must be positive: {line}", "error")
            return redirect(url_for("admin_review_requests"))
        parsed_materials.append((name, quantity, parts[2] if len(parts) > 2 else "pc", parts[3] if len(parts) > 3 else ""))
    if not parsed_materials:
        flash("Add at least one installation material before completing the technical BOM.", "error")
        return redirect(url_for("admin_review_requests"))
    with get_db() as database:
        review = database.execute("SELECT * FROM review_requests WHERE id = ?", (request_id,)).fetchone()
        if not review or review["status"] not in {"technical_review", "site_survey_scheduled"}:
            flash("This request is not in technical review.", "error")
            return redirect(url_for("admin_review_requests"))
        database.execute("DELETE FROM review_request_materials WHERE request_id = ?", (request_id,))
        database.executemany("INSERT INTO review_request_materials (request_id, material_name, quantity, unit, notes) VALUES (?, ?, ?, ?, ?)", [(request_id, *material) for material in parsed_materials])
        database.execute("UPDATE review_requests SET status = 'marketing_bom_review', technical_reviewed_by = ?, technical_reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (session["admin_id"], request_id))
        add_review_message(database, request_id, "admin", session["admin_id"], session["admin_username"], "Technical review, quantity validation and installation materials are complete. The BOM was returned to Marketing.")
    flash("Technical BOM completed and returned to Marketing.", "success")
    return redirect(url_for("admin_review_requests"))


@app.route("/admin/review-requests/<int:request_id>/marketing-proposal", methods=["POST"])
@login_required
def marketing_proposal_complete(request_id):
    validate_csrf()
    require_review_role("admin", "admin_marketing")
    with get_db() as database:
        review = database.execute("SELECT * FROM review_requests WHERE id = ?", (request_id,)).fetchone()
        if review and session.get("admin_role") == "admin_marketing" and review["assigned_marketing_admin_id"] != session["admin_id"]:
            abort(403)
        if not review or review["status"] != "marketing_bom_review":
            flash("This BOM is not ready for Marketing approval.", "error")
            return redirect(url_for("admin_review_requests"))
        items = rows_to_dicts(database.execute("SELECT * FROM review_request_items WHERE request_id = ? ORDER BY id", (request_id,)))
        materials = rows_to_dicts(database.execute("SELECT * FROM review_request_materials WHERE request_id = ? ORDER BY id", (request_id,)))
        bom, proposal = build_review_documents(dict(review), items, materials)
        database.execute("UPDATE review_requests SET status = 'superadmin_review', bom_document = ?, proposal_document = ?, commercial_notes = ?, marketing_reviewed_by = ?, marketing_reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (bom, proposal, request.form.get("commercial_notes", "").strip()[:4000], session["admin_id"], request_id))
        add_review_message(database, request_id, "admin", session["admin_id"], session["admin_username"], "Marketing completed the final BOM and proposal review. The request is awaiting Superadmin approval.")
    flash("BOM and proposal sent to Superadmin for final approval.", "success")
    return redirect(url_for("admin_review_requests"))


@app.route("/admin/review-requests/<int:request_id>/approve", methods=["POST"])
@superadmin_required
def superadmin_review_approve(request_id):
    validate_csrf()
    with get_db() as database:
        review = database.execute("SELECT * FROM review_requests WHERE id = ?", (request_id,)).fetchone()
        if not review:
            abort(404)
        if review["status"] != "superadmin_review":
            flash("This request is not ready for final approval.", "error")
            return redirect(url_for("admin_review_requests"))
        database.execute(
            """UPDATE review_requests SET status = 'approved', superadmin_approved_by = ?,
               superadmin_approved_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (session["admin_id"], request_id),
        )
    notified = False
    try:
        notified = send_review_approved_email(dict(review))
    except Exception:
        app.logger.exception("Review approval email failed")
    if notified:
        with get_db() as database:
            database.execute("UPDATE review_requests SET customer_notified_at = CURRENT_TIMESTAMP WHERE id = ?", (request_id,))
    log_activity("admin", session["admin_id"], session["admin_username"], "review_final_approval", f"Request #{request_id}; email={'sent' if notified else 'not configured'}")
    flash("Request approved." + (" The customer email was sent." if notified else " Configure SMTP to send the customer email."), "success")
    return redirect(url_for("admin_review_requests"))


@app.route("/admin/review-requests/<int:request_id>/<document_type>")
@login_required
def review_document_download(request_id, document_type):
    column = {"bom": "bom_document", "proposal": "proposal_document"}.get(document_type)
    if not column:
        abort(404)
    with get_db() as database:
        review = database.execute(f"SELECT {column} AS document FROM review_requests WHERE id = ?", (request_id,)).fetchone()
    if not review or not review["document"]:
        abort(404)
    mimetype = "text/csv" if document_type == "bom" else "text/plain"
    return Response(review["document"], mimetype=mimetype, headers={"Content-Disposition": f"attachment; filename=VTIC-{document_type}-{request_id:05d}.{'csv' if document_type == 'bom' else 'txt'}"})


@app.route("/account/reviews")
@customer_required
def customer_reviews():
    if not session.get("customer_id"):
        return redirect(url_for("admin_review_requests"))
    with get_db() as database:
        reviews = rows_to_dicts(database.execute(
            """SELECT request.*, COUNT(item.id) AS line_count,
                      COALESCE(SUM(item.quantity), 0) AS item_count
               FROM review_requests request LEFT JOIN review_request_items item ON item.request_id = request.id
               WHERE request.customer_id = ? GROUP BY request.id ORDER BY request.id DESC""",
            (session["customer_id"],),
        ))
        request_ids = [review["id"] for review in reviews]
        messages = []
        if request_ids:
            placeholders = ",".join("?" for _ in request_ids)
            messages = rows_to_dicts(database.execute(
                f"SELECT * FROM review_request_messages WHERE request_id IN ({placeholders}) ORDER BY id",
                request_ids,
            ))
    messages_by_request = {}
    for message in messages:
        messages_by_request.setdefault(message["request_id"], []).append(message)
    for review in reviews:
        if review["status"] in {"submitted", "pending"}:
            review["public_stage"] = "submitted"
        elif review["status"] in {"marketing_review", "awaiting_customer_scope"}:
            review["public_stage"] = "under_review"
        elif review["status"] == "approved":
            review["public_stage"] = "approved"
        else:
            review["public_stage"] = "for_approval"
    stage_counts = {
        stage: sum(review["public_stage"] == stage for review in reviews)
        for stage in ("submitted", "under_review", "for_approval", "approved")
    }
    return render_template("customer_reviews.html", reviews=reviews, messages_by_request=messages_by_request, stage_counts=stage_counts)


@app.route("/admin/catered-customers")
@login_required
def admin_catered_customers():
    if session.get("admin_role") not in {"admin_marketing", "superadmin"}:
        abort(403)
    parameters = ()
    owner_filter = ""
    if session.get("admin_role") == "admin_marketing":
        owner_filter = "WHERE r.assigned_marketing_admin_id = ?"
        parameters = (session["admin_id"],)
    with get_db() as database:
        assignments = rows_to_dicts(
            database.execute(
                f"""SELECT r.assigned_marketing_admin_id, a.username,
                           COALESCE(NULLIF(a.full_name, ''), a.username) AS admin_name,
                           a.avatar_url AS admin_avatar_url,
                           r.customer_id, r.customer_name, r.customer_email,
                           c.avatar_url AS customer_avatar_url,
                           COUNT(r.id) AS request_count,
                           MAX(r.created_at) AS latest_request_at,
                           MAX(CASE WHEN r.status = 'approved' THEN 1 ELSE 0 END) AS has_approved,
                           GROUP_CONCAT(DISTINCT r.status) AS request_statuses
                    FROM review_requests r
                    JOIN admins a ON a.id = r.assigned_marketing_admin_id
                    LEFT JOIN customers c ON c.id = r.customer_id
                    {owner_filter}
                    GROUP BY r.assigned_marketing_admin_id, a.username,
                             a.full_name, a.avatar_url, r.customer_id,
                             r.customer_name, r.customer_email, c.avatar_url
                    ORDER BY admin_name, latest_request_at DESC""",
                parameters,
            )
        )
    admin_groups = {}
    for assignment in assignments:
        admin_groups.setdefault(
            assignment["assigned_marketing_admin_id"],
            {"admin_name": assignment["admin_name"], "username": assignment["username"], "avatar_url": assignment["admin_avatar_url"], "customers": []},
        )["customers"].append(assignment)
    return render_template("admin_catered_customers.html", admin_groups=admin_groups, total_customers=len(assignments))


@app.route("/admin/calendar")
@login_required
def admin_calendar():
    month_value = request.args.get("month", datetime.now().strftime("%Y-%m"))
    try:
        month_date = datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
    except ValueError:
        month_date = datetime.now().date().replace(day=1)
    month_weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(
        month_date.year, month_date.month
    )
    visible_start = month_weeks[0][0]
    visible_end = month_weeks[-1][-1] + timedelta(days=1)
    with get_db() as database:
        events = rows_to_dicts(
            database.execute(
                """SELECT * FROM calendar_events
                   WHERE starts_at >= ? AND starts_at < ? ORDER BY starts_at""",
                (visible_start.isoformat(), visible_end.isoformat()),
            )
        )
    events_by_date = {}
    for event in events:
        events_by_date.setdefault(event["starts_at"][:10], []).append(event)
    previous_month = (month_date - timedelta(days=1)).replace(day=1)
    next_month = (month_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    return render_template(
        "admin_calendar.html",
        month_date=month_date,
        month_weeks=month_weeks,
        events_by_date=events_by_date,
        previous_month=previous_month.strftime("%Y-%m"),
        next_month=next_month.strftime("%Y-%m"),
        today=datetime.now().date().isoformat(),
    )


@app.route("/admin/calendar/events/new", methods=["POST"])
@login_required
def admin_calendar_event_create():
    validate_csrf()
    title = request.form.get("title", "").strip()
    starts_at = request.form.get("starts_at", "").strip()
    if not title or not starts_at:
        flash("Event title and date are required.", "error")
        return redirect(url_for("admin_calendar"))
    with get_db() as database:
        cursor = database.execute(
            """INSERT INTO calendar_events
               (event_type, title, starts_at, location, notes, created_by)
               VALUES ('meeting', ?, ?, ?, ?, ?)""",
            (title, starts_at, request.form.get("location", "").strip(),
             request.form.get("notes", "").strip(), session["admin_id"]),
        )
    log_activity("admin", session["admin_id"], session["admin_username"],
                 "calendar_event_create", f"{title} (ID #{cursor.lastrowid})")
    flash("Calendar event added.", "success")
    return redirect(url_for("admin_calendar", month=starts_at[:7]))


def product_form_values(existing_image_url=None):
    price_text = request.form.get("price", "").strip()
    image_url = request.form.get("image_url", "").strip() or existing_image_url
    if request.form.get("remove_image") == "1":
        image_url = None
    uploaded_image = save_product_image(request.files.get("image_file"))
    image_url = uploaded_image or image_url
    return (
        request.form.get("brand", "").strip(),
        request.form.get("name", "").strip(),
        request.form.get("category", "").strip(),
        float(price_text) if price_text else None,
        request.form.get("description", "").strip(),
        request.form.get("source", "Partner quotation").strip(),
        request.form.get("color", "#e8f0ff").strip(),
        image_url,
    )


def get_manufacturers():
    with get_db() as database:
        return rows_to_dicts(
            database.execute("SELECT * FROM manufacturers ORDER BY name COLLATE NOCASE")
        )


def manufacturer_exists(name):
    with get_db() as database:
        return (
            database.execute(
                "SELECT 1 FROM manufacturers WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            is not None
        )


def manufacturer_products(name):
    with get_db() as database:
        return rows_to_dicts(
            database.execute(
                """SELECT * FROM products WHERE brand = ? COLLATE NOCASE
                   ORDER BY updated_at DESC, name COLLATE NOCASE""",
                (name,),
            )
        )


def render_manufacturer_workspace(manufacturer):
    return render_template(
        "admin_manufacturer_form.html",
        manufacturer=dict(manufacturer),
        products=manufacturer_products(manufacturer["name"]),
        categories=get_catalog_categories(include_all=False),
    )


@app.route("/admin/products/new", methods=["GET", "POST"])
@login_required
def admin_product_new():
    if request.method == "POST":
        validate_csrf()
        try:
            values = product_form_values()
        except ValueError as error:
            flash(str(error), "error")
            return render_template(
                "admin_product_form.html",
                product=None,
                categories=get_catalog_categories(include_all=False),
                manufacturers=get_manufacturers(),
            )
        if not all((values[0], values[1], values[2], values[4])):
            flash("Brand, name, category and description are required.", "error")
        elif not manufacturer_exists(values[0]):
            flash("Select a manufacturer from the list.", "error")
        else:
            with get_db() as database:
                cursor = database.execute(
                    """INSERT INTO products
                       (brand, name, category, price, description, source, color, image_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
                )
                product_id = cursor.lastrowid
            log_activity(
                "admin", session["admin_id"], session["admin_username"],
                "product_create", f"Product #{product_id}: {values[1]}"
            )
            flash("Product added successfully.", "success")
            return redirect(url_for("admin_dashboard"))
    return render_template(
        "admin_product_form.html",
        product=None,
        categories=get_catalog_categories(include_all=False),
        manufacturers=get_manufacturers(),
    )


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def admin_product_edit(product_id):
    with get_db() as database:
        row = database.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    if not row:
        abort(404)
    if request.method == "POST":
        validate_csrf()
        try:
            values = product_form_values(row["image_url"])
        except ValueError as error:
            flash(str(error), "error")
            return render_template(
                "admin_product_form.html",
                product=dict(row),
                categories=get_catalog_categories(include_all=False),
                manufacturers=get_manufacturers(),
            )
        if not manufacturer_exists(values[0]):
            flash("Select a manufacturer from the list.", "error")
            return render_template(
                "admin_product_form.html",
                product=dict(row),
                categories=get_catalog_categories(include_all=False),
                manufacturers=get_manufacturers(),
            )
        with get_db() as database:
            database.execute(
                """UPDATE products SET brand=?, name=?, category=?, price=?, description=?,
                   source=?, color=?, image_url=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (*values, product_id),
            )
        log_activity(
            "admin", session["admin_id"], session["admin_username"],
            "product_update", f"Product #{product_id}: {values[1]}"
        )
        flash("Product updated successfully.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template(
        "admin_product_form.html",
        product=dict(row),
        categories=get_catalog_categories(include_all=False),
        manufacturers=get_manufacturers(),
    )


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
@login_required
def admin_product_delete(product_id):
    validate_csrf()
    with get_db() as database:
        product = database.execute(
            "SELECT name FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        database.execute("DELETE FROM products WHERE id = ?", (product_id,))
    if product:
        log_activity(
            "admin", session["admin_id"], session["admin_username"],
            "product_delete", f"Product #{product_id}: {product['name']}"
        )
    flash("Product deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/gallery")
@superadmin_required
def admin_gallery():
    with get_db() as database:
        items = rows_to_dicts(
            database.execute(
                """SELECT * FROM gallery_items
                   ORDER BY display_order ASC, id DESC"""
            )
        )
    for item in items:
        image_url = item["image_url"]
        item["image_src"] = (
            image_url
            if image_url.startswith(("/", "http://", "https://"))
            else url_for("static", filename=image_url)
        )
    albums = {}
    standalone_items = []
    for item in items:
        album_name = item.get("album_name", "").strip()
        if album_name:
            album = albums.setdefault(
                album_name,
                {
                    "name": album_name,
                    "category": item["category"],
                    "event_date": item["event_date"],
                    "description": item["description"],
                    "items": [],
                },
            )
            album["items"].append(item)
        else:
            standalone_items.append(item)
    for album in albums.values():
        cover = next(
            (item for item in album["items"] if item["is_album_cover"]),
            album["items"][0],
        )
        album["cover_src"] = cover["image_src"]
        album["cover_id"] = cover["id"]
        album["sort_order"] = min(item["display_order"] for item in album["items"])
    gallery_records = [
        {"kind": "album", "value": album, "sort_order": album["sort_order"]}
        for album in albums.values()
    ] + [
        {"kind": "item", "value": item, "sort_order": item["display_order"]}
        for item in standalone_items
    ]
    gallery_records.sort(key=lambda record: record["sort_order"])
    return render_template(
        "admin_gallery.html",
        gallery_items=items,
        gallery_albums=list(albums.values()),
        standalone_items=standalone_items,
        gallery_records=gallery_records,
    )


@app.route("/admin/gallery/album/cover", methods=["POST"])
@superadmin_required
def admin_gallery_album_cover():
    validate_csrf()
    album_name = request.form.get("album_name", "").strip()
    try:
        cover_id = int(request.form.get("cover_id", ""))
    except ValueError:
        cover_id = 0
    with get_db() as database:
        cover = database.execute(
            "SELECT id FROM gallery_items WHERE id = ? AND album_name = ?",
            (cover_id, album_name),
        ).fetchone()
        if not album_name or not cover:
            abort(400)
        database.execute(
            "UPDATE gallery_items SET is_album_cover = 0 WHERE album_name = ?",
            (album_name,),
        )
        database.execute(
            "UPDATE gallery_items SET is_album_cover = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (cover_id,),
        )
    log_activity("admin", session["admin_id"], session["admin_username"], "gallery_album_cover", album_name)
    flash("Album thumbnail updated.", "success")
    return redirect(url_for("admin_gallery"))


@app.route("/admin/gallery/new", methods=["POST"])
@superadmin_required
def admin_gallery_create():
    validate_csrf()
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip() or "Behind the scenes"
    try:
        image_url = save_portfolio_image(request.files.get("image_file"))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin_gallery"))
    if not title or not image_url:
        flash("A title and picture are required.", "error")
    else:
        with get_db() as database:
            cursor = database.execute(
                """INSERT INTO gallery_items
                   (title, category, description, event_date, album_name, image_url, display_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    title[:160], category[:80],
                    request.form.get("description", "").strip()[:1000],
                    request.form.get("event_date", "").strip() or None,
                    request.form.get("album_name", "").strip()[:160],
                    image_url, 0,
                ),
            )
            move_gallery_item(database, cursor.lastrowid, portfolio_order_value() or 1)
        log_activity("admin", session["admin_id"], session["admin_username"], "gallery_create", title)
        flash("Gallery picture uploaded.", "success")
    return redirect(url_for("admin_gallery"))


@app.route("/admin/gallery/<int:item_id>/edit", methods=["POST"])
@superadmin_required
def admin_gallery_edit(item_id):
    validate_csrf()
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "").strip() or "Behind the scenes"
    try:
        uploaded_image = save_portfolio_image(request.files.get("image_file"))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin_gallery"))
    with get_db() as database:
        current = database.execute(
            "SELECT * FROM gallery_items WHERE id = ?", (item_id,)
        ).fetchone()
        if not current:
            abort(404)
        if not title:
            flash("A title is required.", "error")
            return redirect(url_for("admin_gallery"))
        database.execute(
            """UPDATE gallery_items
               SET title = ?, category = ?, description = ?, event_date = ?, album_name = ?,
                   image_url = ?, display_order = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                title[:160], category[:80],
                request.form.get("description", "").strip()[:1000],
                request.form.get("event_date", "").strip() or None,
                request.form.get("album_name", "").strip()[:160],
                uploaded_image or current["image_url"], current["display_order"], item_id,
            ),
        )
        move_gallery_item(database, item_id, portfolio_order_value() or 1)
    log_activity("admin", session["admin_id"], session["admin_username"], "gallery_update", title)
    flash("Gallery entry updated.", "success")
    return redirect(url_for("admin_gallery"))


@app.route("/admin/gallery/<int:item_id>/delete", methods=["POST"])
@superadmin_required
def admin_gallery_delete(item_id):
    validate_csrf()
    with get_db() as database:
        item = database.execute(
            "SELECT title FROM gallery_items WHERE id = ?", (item_id,)
        ).fetchone()
        if not item:
            abort(404)
        database.execute("DELETE FROM gallery_items WHERE id = ?", (item_id,))
        normalize_gallery_order(database)
    log_activity("admin", session["admin_id"], session["admin_username"], "gallery_delete", item["title"])
    flash("Gallery entry deleted.", "success")
    return redirect(url_for("admin_gallery"))


@app.route("/admin/portfolio")
@superadmin_required
def admin_portfolio():
    with get_db() as database:
        clients = rows_to_dicts(database.execute(
            "SELECT * FROM portfolio_clients ORDER BY display_order, name COLLATE NOCASE"
        ))
        groups = rows_to_dicts(database.execute(
            "SELECT * FROM portfolio_partner_groups ORDER BY display_order, name COLLATE NOCASE"
        ))
        partners = rows_to_dicts(database.execute(
            """SELECT p.*, g.name AS group_name FROM portfolio_partners p
               JOIN portfolio_partner_groups g ON g.id = p.group_id
               ORDER BY g.display_order, p.display_order, p.name COLLATE NOCASE"""
        ))
    for client in clients:
        image_url = client["image_url"] or "images/technology-eye.webp"
        client["image_src"] = image_url if image_url.startswith(("/", "http://", "https://")) else url_for("static", filename=image_url)
    for partner in partners:
        logo_url = partner["logo_url"]
        partner["logo_src"] = (logo_url if logo_url.startswith(("/", "http://", "https://")) else url_for("static", filename=logo_url)) if logo_url else ""
    return render_template("admin_portfolio.html", clients=clients, groups=groups, partners=partners)


def portfolio_order_value():
    try:
        return max(0, int(request.form.get("display_order", "0")))
    except ValueError:
        return 0


def normalize_gallery_order(database, ordered_ids=None):
    """Keep gallery positions contiguous and unique, starting at one."""
    if ordered_ids is None:
        ordered_ids = [
            row["id"]
            for row in database.execute(
                """SELECT id FROM gallery_items
                   ORDER BY CASE WHEN display_order < 1 THEN 2147483647 ELSE display_order END,
                            created_at DESC, id DESC"""
            ).fetchall()
        ]
    database.executemany(
        "UPDATE gallery_items SET display_order = ? WHERE id = ?",
        [(position, item_id) for position, item_id in enumerate(ordered_ids, start=1)],
    )


def move_gallery_item(database, item_id, requested_position):
    """Move one item and shift every surrounding position without overlaps."""
    ordered_ids = [
        row["id"]
        for row in database.execute(
            """SELECT id FROM gallery_items
               ORDER BY CASE WHEN display_order < 1 THEN 2147483647 ELSE display_order END,
                        created_at DESC, id DESC"""
        ).fetchall()
        if row["id"] != item_id
    ]
    position = max(1, min(requested_position, len(ordered_ids) + 1))
    ordered_ids.insert(position - 1, item_id)
    normalize_gallery_order(database, ordered_ids)


@app.route("/admin/portfolio/clients/new", methods=["POST"])
@superadmin_required
def admin_portfolio_client_create():
    validate_csrf()
    name = request.form.get("name", "").strip()
    sector = request.form.get("sector", "").strip()
    try:
        image_url = save_portfolio_image(request.files.get("image_file")) or request.form.get("image_url", "").strip()
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin_portfolio"))
    if not name or not sector:
        flash("Client name and sector are required.", "error")
    else:
        with get_db() as database:
            database.execute(
                """INSERT INTO portfolio_clients
                   (name, sector, image_url, scope, display_order) VALUES (?, ?, ?, ?, ?)""",
                (name, sector, image_url,
                 request.form.get("scope", "").strip(), portfolio_order_value()),
            )
        log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_client_create", name)
        flash(f"{name} was added to the client gallery.", "success")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/portfolio/clients/<int:item_id>/edit", methods=["POST"])
@superadmin_required
def admin_portfolio_client_edit(item_id):
    validate_csrf()
    name = request.form.get("name", "").strip()
    sector = request.form.get("sector", "").strip()
    try:
        uploaded_image = save_portfolio_image(request.files.get("image_file"))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin_portfolio"))
    if not name or not sector:
        flash("Client name and sector are required.", "error")
    else:
        with get_db() as database:
            if not database.execute("SELECT id FROM portfolio_clients WHERE id = ?", (item_id,)).fetchone():
                abort(404)
            current = database.execute("SELECT image_url FROM portfolio_clients WHERE id = ?", (item_id,)).fetchone()
            image_url = uploaded_image or request.form.get("image_url", "").strip() or current["image_url"]
            database.execute(
                """UPDATE portfolio_clients SET name = ?, sector = ?, image_url = ?, scope = ?,
                   display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (name, sector, image_url,
                 request.form.get("scope", "").strip(), portfolio_order_value(), item_id),
            )
        log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_client_update", name)
        flash("Client entry updated.", "success")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/portfolio/clients/<int:item_id>/delete", methods=["POST"])
@superadmin_required
def admin_portfolio_client_delete(item_id):
    validate_csrf()
    with get_db() as database:
        item = database.execute("SELECT name FROM portfolio_clients WHERE id = ?", (item_id,)).fetchone()
        if not item:
            abort(404)
        database.execute("DELETE FROM portfolio_clients WHERE id = ?", (item_id,))
    log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_client_delete", item["name"])
    flash("Client entry deleted.", "success")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/portfolio/groups/new", methods=["POST"])
@superadmin_required
def admin_portfolio_group_create():
    validate_csrf()
    name = request.form.get("name", "").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", request.form.get("slug", "").strip().lower()).strip("-")
    if not name or not slug:
        flash("Group name and slug are required.", "error")
    else:
        try:
            with get_db() as database:
                database.execute(
                    """INSERT INTO portfolio_partner_groups
                       (slug, name, summary, display_order) VALUES (?, ?, ?, ?)""",
                    (slug, name, request.form.get("summary", "").strip(), portfolio_order_value()),
                )
            log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_group_create", name)
            flash("Partner category added.", "success")
        except DB_INTEGRITY_ERRORS:
            flash("That partner-category slug already exists.", "error")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/portfolio/groups/<int:item_id>/edit", methods=["POST"])
@superadmin_required
def admin_portfolio_group_edit(item_id):
    validate_csrf()
    name = request.form.get("name", "").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", request.form.get("slug", "").strip().lower()).strip("-")
    if not name or not slug:
        flash("Group name and slug are required.", "error")
    else:
        try:
            with get_db() as database:
                if not database.execute("SELECT id FROM portfolio_partner_groups WHERE id = ?", (item_id,)).fetchone():
                    abort(404)
                database.execute(
                    """UPDATE portfolio_partner_groups SET slug = ?, name = ?, summary = ?,
                       display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                    (slug, name, request.form.get("summary", "").strip(), portfolio_order_value(), item_id),
                )
            log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_group_update", name)
            flash("Partner category updated.", "success")
        except DB_INTEGRITY_ERRORS:
            flash("That partner-category slug already exists.", "error")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/portfolio/groups/<int:item_id>/delete", methods=["POST"])
@superadmin_required
def admin_portfolio_group_delete(item_id):
    validate_csrf()
    with get_db() as database:
        item = database.execute("SELECT name FROM portfolio_partner_groups WHERE id = ?", (item_id,)).fetchone()
        if not item:
            abort(404)
        database.execute("DELETE FROM portfolio_partners WHERE group_id = ?", (item_id,))
        database.execute("DELETE FROM portfolio_partner_groups WHERE id = ?", (item_id,))
    log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_group_delete", item["name"])
    flash("Partner category and its entries were deleted.", "success")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/portfolio/partners/new", methods=["POST"])
@superadmin_required
def admin_portfolio_partner_create():
    validate_csrf()
    name = request.form.get("name", "").strip()
    try:
        logo_url = save_portfolio_image(request.files.get("logo_file")) or request.form.get("logo_url", "").strip()
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin_portfolio"))
    try:
        group_id = int(request.form.get("group_id", ""))
    except ValueError:
        group_id = 0
    with get_db() as database:
        group = database.execute("SELECT id FROM portfolio_partner_groups WHERE id = ?", (group_id,)).fetchone()
        if not name or not group:
            flash("Partner name and a valid category are required.", "error")
            return redirect(url_for("admin_portfolio"))
        database.execute(
            """INSERT INTO portfolio_partners
               (group_id, name, website_url, logo_url, display_order) VALUES (?, ?, ?, ?, ?)""",
            (group_id, name, request.form.get("website_url", "").strip() or "#",
             logo_url, portfolio_order_value()),
        )
    log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_partner_create", name)
    flash(f"{name} was added to the partner gallery.", "success")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/portfolio/partners/<int:item_id>/edit", methods=["POST"])
@superadmin_required
def admin_portfolio_partner_edit(item_id):
    validate_csrf()
    name = request.form.get("name", "").strip()
    try:
        uploaded_logo = save_portfolio_image(request.files.get("logo_file"))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin_portfolio"))
    try:
        group_id = int(request.form.get("group_id", ""))
    except ValueError:
        group_id = 0
    with get_db() as database:
        partner = database.execute("SELECT id FROM portfolio_partners WHERE id = ?", (item_id,)).fetchone()
        group = database.execute("SELECT id FROM portfolio_partner_groups WHERE id = ?", (group_id,)).fetchone()
        if not partner:
            abort(404)
        if not name or not group:
            flash("Partner name and a valid category are required.", "error")
            return redirect(url_for("admin_portfolio"))
        current = database.execute("SELECT logo_url FROM portfolio_partners WHERE id = ?", (item_id,)).fetchone()
        logo_url = "" if request.form.get("remove_logo") == "1" else (
            uploaded_logo or request.form.get("logo_url", "").strip() or current["logo_url"]
        )
        database.execute(
            """UPDATE portfolio_partners SET group_id = ?, name = ?, website_url = ?, logo_url = ?,
               display_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (group_id, name, request.form.get("website_url", "").strip() or "#",
             logo_url, portfolio_order_value(), item_id),
        )
    log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_partner_update", name)
    flash("Partner entry updated.", "success")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/portfolio/partners/<int:item_id>/delete", methods=["POST"])
@superadmin_required
def admin_portfolio_partner_delete(item_id):
    validate_csrf()
    with get_db() as database:
        item = database.execute("SELECT name FROM portfolio_partners WHERE id = ?", (item_id,)).fetchone()
        if not item:
            abort(404)
        database.execute("DELETE FROM portfolio_partners WHERE id = ?", (item_id,))
    log_activity("admin", session["admin_id"], session["admin_username"], "portfolio_partner_delete", item["name"])
    flash("Partner entry deleted.", "success")
    return redirect(url_for("admin_portfolio"))


@app.route("/admin/manufacturers", methods=["GET", "POST"])
@login_required
def admin_manufacturers():
    if request.method == "POST":
        validate_csrf()
        name = request.form.get("name", "").strip()
        logo_url = request.form.get("logo_url", "").strip() or None
        try:
            uploaded_logo = save_manufacturer_logo(request.files.get("logo_file"))
            logo_url = uploaded_logo or logo_url
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("admin_manufacturers"))
        if not name:
            flash("Manufacturer name is required.", "error")
        else:
            try:
                with get_db() as database:
                    database.execute(
                        "INSERT INTO manufacturers (name, logo_url) VALUES (?, ?)",
                        (name, logo_url),
                    )
                log_activity(
                    "admin", session["admin_id"], session["admin_username"],
                    "manufacturer_create", name
                )
                flash(f"{name} was added to the manufacturer list.", "success")
            except DB_INTEGRITY_ERRORS:
                flash("That manufacturer already exists.", "error")
        return redirect(url_for("admin_manufacturers"))

    with get_db() as database:
        manufacturers = rows_to_dicts(
            database.execute(
                """SELECT m.id, m.name, m.logo_url, m.created_at, COUNT(p.id) AS product_count
                   FROM manufacturers m
                   LEFT JOIN products p ON p.brand = m.name COLLATE NOCASE
                   GROUP BY m.id, m.name, m.created_at
                   ORDER BY m.name COLLATE NOCASE"""
            )
        )
    return render_template("admin_manufacturers.html", manufacturers=manufacturers)


@app.route("/admin/manufacturers/<int:manufacturer_id>/edit", methods=["GET", "POST"])
@login_required
def admin_manufacturer_edit(manufacturer_id):
    with get_db() as database:
        row = database.execute(
            "SELECT * FROM manufacturers WHERE id = ?", (manufacturer_id,)
        ).fetchone()
    if not row:
        abort(404)

    if request.method == "POST":
        validate_csrf()
        name = request.form.get("name", "").strip()
        logo_url = request.form.get("logo_url", "").strip() or row["logo_url"]
        if request.form.get("remove_logo") == "1":
            logo_url = None
        try:
            uploaded_logo = save_manufacturer_logo(request.files.get("logo_file"))
            logo_url = uploaded_logo or logo_url
        except ValueError as error:
            flash(str(error), "error")
            return render_manufacturer_workspace(row)
        if not name:
            flash("Manufacturer name is required.", "error")
        else:
            try:
                with get_db() as database:
                    database.execute("BEGIN")
                    database.execute(
                        "UPDATE products SET brand = ?, updated_at = CURRENT_TIMESTAMP WHERE brand = ? COLLATE NOCASE",
                        (name, row["name"]),
                    )
                    database.execute(
                        "UPDATE manufacturers SET name = ?, logo_url = ? WHERE id = ?",
                        (name, logo_url, manufacturer_id),
                    )
                log_activity(
                    "admin", session["admin_id"], session["admin_username"],
                    "manufacturer_update", f"{row['name']} → {name}"
                )
                flash("Manufacturer updated successfully.", "success")
                return redirect(url_for("admin_manufacturers"))
            except DB_INTEGRITY_ERRORS:
                flash("Another manufacturer already uses that name.", "error")
    return render_manufacturer_workspace(row)


@app.route("/admin/manufacturers/products-template.csv")
@login_required
def admin_manufacturer_csv_template():
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["name", "category", "price", "description", "source"])
    writer.writerow(
        [
            "Example Managed Switch", "Switches", "24990.00",
            "24-port managed enterprise switch.", "Partner quotation",
        ]
    )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=vtic-products-template.csv"},
    )


@app.route(
    "/admin/manufacturers/<int:manufacturer_id>/products/import", methods=["POST"]
)
@login_required
def admin_manufacturer_product_import(manufacturer_id):
    validate_csrf()
    upload = request.files.get("csv_file")
    if not upload or not upload.filename:
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    if not upload.filename.lower().endswith(".csv"):
        flash("The import file must use the .csv extension.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    with get_db() as database:
        manufacturer = database.execute(
            "SELECT * FROM manufacturers WHERE id = ?", (manufacturer_id,)
        ).fetchone()
        if not manufacturer:
            abort(404)
        existing_products = {
            row["name"].casefold(): dict(row)
            for row in database.execute(
                """SELECT id, name, price FROM products
                   WHERE brand = ? COLLATE NOCASE""",
                (manufacturer["name"],),
            )
        }
    raw_content = upload.stream.read()
    try:
        if raw_content.startswith((b"\xff\xfe", b"\xfe\xff")):
            content = raw_content.decode("utf-16")
        else:
            try:
                content = raw_content.decode("utf-8-sig")
            except UnicodeDecodeError:
                content = raw_content.decode("cp1252")
    except UnicodeDecodeError:
        flash(
            "The CSV text encoding could not be read. Export it as CSV UTF-8 or Windows CSV.",
            "error",
        )
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))

    if "\x00" in content:
        flash(
            "The uploaded file is not a readable CSV. Export the worksheet as CSV and try again.",
            "error",
        )
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    reader = csv.DictReader(io.StringIO(content))
    required_headers = {"name", "category", "description"}
    headers = {header.strip().lower() for header in (reader.fieldnames or []) if header}
    if not required_headers.issubset(headers):
        flash("CSV headers must include name, category, and description.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))

    records = []
    price_updates = []
    errors = []
    imported_names = set()
    skipped_duplicates = 0
    skipped_invalid = 0
    for row_number, raw_row in enumerate(reader, start=2):
        if row_number > 5001:
            errors.append("Rows after the 5,000-product import limit were not processed.")
            break
        row = {(key or "").strip().lower(): (value or "").strip() for key, value in raw_row.items()}
        if not any(row.values()):
            continue
        name = row.get("name", "")
        category = normalize_product_category(row.get("category", ""))
        description = row.get("description", "")
        price_text = row.get("price", "")
        price = parse_optional_csv_price(price_text)
        name_key = name.casefold()
        row_errors = []
        if not name:
            row_errors.append(f"Row {row_number}: product name is required.")
        elif name_key in imported_names:
            skipped_duplicates += 1
            continue
        if not category:
            row_errors.append(f"Row {row_number}: category is required.")
        if not description:
            row_errors.append(f"Row {row_number}: description is required.")
        if row_errors:
            skipped_invalid += 1
            errors.extend(row_errors)
            continue
        imported_names.add(name_key)
        existing_product = existing_products.get(name_key)
        if existing_product:
            if price is not None and existing_product["price"] != price:
                price_updates.append(
                    (
                        price,
                        row.get("source") or "Partner quotation",
                        existing_product["id"],
                    )
                )
            else:
                skipped_duplicates += 1
            continue
        records.append(
            (
                manufacturer["name"], name, category, price, description,
                row.get("source") or "Partner quotation", "#e8f0ff", None,
            )
        )
    if not records and not price_updates:
        if skipped_duplicates:
            message = f"No new products were imported. Skipped {skipped_duplicates} duplicate product(s)."
            if skipped_invalid:
                message += f" Skipped {skipped_invalid} invalid row(s)."
            flash(message, "success")
        elif errors:
            preview = " ".join(errors[:8])
            if len(errors) > 8:
                preview += f" Plus {len(errors) - 8} more error(s)."
            flash(f"No valid products were found. {preview}", "error")
        else:
            flash("The CSV does not contain any product rows.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    with get_db() as database:
        if records:
            database.executemany(
                """INSERT INTO products
                   (brand, name, category, price, description, source, color, image_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                records,
            )
        if price_updates:
            database.executemany(
                """UPDATE products SET price = ?, source = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                price_updates,
            )
    log_activity(
        "admin", session["admin_id"], session["admin_username"],
        "product_csv_import",
        f"{manufacturer['name']}: {len(records)} added, {len(price_updates)} prices updated",
    )
    message = f"Imported {len(records)} new product(s) for {manufacturer['name']}."
    if price_updates:
        message += f" Updated prices for {len(price_updates)} existing product(s)."
    if skipped_duplicates:
        message += f" Skipped {skipped_duplicates} duplicate product(s)."
    if skipped_invalid:
        message += f" Skipped {skipped_invalid} invalid row(s)."
    flash(message, "success")
    if errors:
        preview = " ".join(errors[:5])
        if len(errors) > 5:
            preview += f" Plus {len(errors) - 5} more issue(s)."
        flash(f"Some rows need attention: {preview}", "error")
    return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))


@app.route(
    "/admin/manufacturers/<int:manufacturer_id>/products/<int:product_id>/quick-edit",
    methods=["POST"],
)
@login_required
def admin_manufacturer_product_quick_edit(manufacturer_id, product_id):
    validate_csrf()
    with get_db() as database:
        manufacturer = database.execute(
            "SELECT * FROM manufacturers WHERE id = ?", (manufacturer_id,)
        ).fetchone()
        product = database.execute(
            """SELECT * FROM products
               WHERE id = ? AND brand = (SELECT name FROM manufacturers WHERE id = ?)
               COLLATE NOCASE""",
            (product_id, manufacturer_id),
        ).fetchone()
    if not manufacturer or not product:
        abort(404)
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()
    source = request.form.get("source", "").strip() or "Partner quotation"
    price_text = request.form.get("price", "").strip()
    if not name or not description or not category:
        flash("Product name, valid category, and description are required.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    try:
        price = float(price_text.replace(",", "")) if price_text else None
        if price is not None and price < 0:
            raise ValueError
    except ValueError:
        flash("Price must be a positive number or left blank.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    image_url = request.form.get("image_url", "").strip() or product["image_url"]
    if request.form.get("remove_image") == "1":
        image_url = None
    try:
        uploaded_image = save_product_image(request.files.get("image_file"))
        image_url = uploaded_image or image_url
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    with get_db() as database:
        database.execute(
            """UPDATE products SET name = ?, category = ?, price = ?,
               description = ?, source = ?, image_url = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (name, category, price, description, source, image_url, product_id),
        )
    log_activity(
        "admin", session["admin_id"], session["admin_username"],
        "product_quick_update", f"Product #{product_id}: {name}"
    )
    flash(f"{name} was updated.", "success")
    return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))


@app.route(
    "/admin/manufacturers/<int:manufacturer_id>/products/batch-delete",
    methods=["POST"],
)
@login_required
def admin_manufacturer_products_batch_delete(manufacturer_id):
    validate_csrf()
    product_ids = []
    for value in request.form.getlist("product_ids"):
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in product_ids:
            product_ids.append(product_id)

    if not product_ids:
        flash("Select at least one product to delete.", "error")
        return redirect(
            url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id)
        )

    placeholders = ",".join("?" for _ in product_ids)
    with get_db() as database:
        manufacturer = database.execute(
            "SELECT name FROM manufacturers WHERE id = ?", (manufacturer_id,)
        ).fetchone()
        if not manufacturer:
            abort(404)
        products = rows_to_dicts(
            database.execute(
                f"""SELECT id, name FROM products
                    WHERE id IN ({placeholders}) AND brand = ? COLLATE NOCASE""",
                (*product_ids, manufacturer["name"]),
            )
        )
        authorized_ids = [product["id"] for product in products]
        if authorized_ids:
            authorized_placeholders = ",".join("?" for _ in authorized_ids)
            database.execute(
                f"DELETE FROM products WHERE id IN ({authorized_placeholders})",
                authorized_ids,
            )

    if not products:
        flash("None of the selected products belong to this manufacturer.", "error")
    else:
        deleted_names = ", ".join(product["name"] for product in products[:5])
        if len(products) > 5:
            deleted_names += f" and {len(products) - 5} more"
        log_activity(
            "admin",
            session["admin_id"],
            session["admin_username"],
            "product_batch_delete",
            f"{manufacturer['name']}: {len(products)} product(s) — {deleted_names}",
        )
        flash(f"Deleted {len(products)} selected product(s).", "success")
    return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))


@app.route("/admin/manufacturers/<int:manufacturer_id>/delete", methods=["POST"])
@login_required
def admin_manufacturer_delete(manufacturer_id):
    validate_csrf()
    with get_db() as database:
        manufacturer = database.execute(
            "SELECT name FROM manufacturers WHERE id = ?", (manufacturer_id,)
        ).fetchone()
        if not manufacturer:
            abort(404)
        product_count = database.execute(
            "SELECT COUNT(*) FROM products WHERE brand = ? COLLATE NOCASE",
            (manufacturer["name"],),
        ).fetchone()[0]
        if product_count:
            flash(
                f"{manufacturer['name']} cannot be deleted because it is used by {product_count} product(s).",
                "error",
            )
        else:
            database.execute(
                "DELETE FROM manufacturers WHERE id = ?", (manufacturer_id,)
            )
            deleted_name = manufacturer["name"]
            flash("Manufacturer deleted.", "success")
    if not product_count:
        log_activity(
            "admin", session["admin_id"], session["admin_username"],
            "manufacturer_delete", deleted_name
        )
    return redirect(url_for("admin_manufacturers"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
