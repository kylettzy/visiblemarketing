import os
import json
import csv
import io
import secrets
import sqlite3
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
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

APP_ROOT = Path(__file__).resolve().parent
load_dotenv(APP_ROOT / ".env")

IS_VERCEL = bool(os.environ.get("VERCEL"))
DEFAULT_RUNTIME_ROOT = Path("/tmp/vtic-store") if IS_VERCEL else APP_ROOT
RUNTIME_ROOT = Path(os.environ.get("VTIC_RUNTIME_ROOT", DEFAULT_RUNTIME_ROOT))
STATIC_ROOT = APP_ROOT / "static"

# Vercel's deployed bundle is read-only. Flask's normal static handler is also
# bypassed by Vercel, so static assets are served explicitly from the bundle and
# runtime writes are confined to /tmp.
app = Flask(__name__, static_folder=None)
app.config["SECRET_KEY"] = os.environ.get(
    "VTIC_SECRET_KEY", "development-only-change-me"
)
DATABASE = Path(os.environ.get("VTIC_DATABASE_PATH", RUNTIME_ROOT / "vtic_store.db"))
UPLOAD_ROOT = RUNTIME_ROOT / "uploads"
MANUFACTURER_UPLOADS = UPLOAD_ROOT / "manufacturers"
PRODUCT_UPLOADS = UPLOAD_ROOT / "products"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
MANUFACTURER_UPLOADS.mkdir(parents=True, exist_ok=True)
PRODUCT_UPLOADS.mkdir(parents=True, exist_ok=True)


@app.route("/static/<path:filename>", endpoint="static")
def static_files(filename):
    return send_from_directory(STATIC_ROOT, filename)


@app.route("/uploads/<kind>/<path:filename>")
def uploaded_file(kind, filename):
    upload_directories = {
        "manufacturers": MANUFACTURER_UPLOADS,
        "products": PRODUCT_UPLOADS,
    }
    directory = upload_directories.get(kind)
    if directory is None:
        abort(404)
    return send_from_directory(directory, filename)


def get_db():
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def hide_customer_pricing(products):
    """Return storefront-safe products without confidential commercial data."""
    safe_products = []
    for product in products:
        safe_product = dict(product)
        safe_product["price"] = None
        safe_product["source"] = "Pricing available after VTIC review"
        safe_products.append(safe_product)
    return safe_products


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
        return view(*args, **kwargs)

    return wrapped_view


def customer_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("customer_id") and not session.get("admin_id"):
            return redirect(url_for("customer_login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped_view


def superadmin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        if session.get("admin_role") != "superadmin":
            abort(403)
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
    "Routers",
    "Switches",
    "Cybersecurity",
    "Cabling",
    "Fiber",
    "CCTV",
    "Communications",
    "Servers & Cloud",
    "Cloud Software",
    "Storage",
    "Network Management",
    "Tools",
]


def initialize_database():
    with get_db() as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'superadmin',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT
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
            CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
            CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
            """
        )
        manufacturer_columns = {
            row[1] for row in database.execute("PRAGMA table_info(manufacturers)")
        }
        if "logo_url" not in manufacturer_columns:
            database.execute("ALTER TABLE manufacturers ADD COLUMN logo_url TEXT")
        admin_columns = {row[1] for row in database.execute("PRAGMA table_info(admins)")}
        if "role" not in admin_columns:
            database.execute(
                "ALTER TABLE admins ADD COLUMN role TEXT NOT NULL DEFAULT 'superadmin'"
            )
        database.execute("UPDATE admins SET role = 'superadmin' WHERE role IS NULL")
        review_columns = {
            row[1] for row in database.execute("PRAGMA table_info(review_requests)")
        }
        if "ai_solution_option_id" not in review_columns:
            database.execute(
                "ALTER TABLE review_requests ADD COLUMN ai_solution_option_id INTEGER"
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
        admin_username = os.environ.get("VTIC_ADMIN_USERNAME", "admin")
        admin_password = os.environ.get("VTIC_ADMIN_PASSWORD", "ChangeMe-VTIC-2026!")
        if database.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            database.execute(
                "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                (admin_username, generate_password_hash(admin_password)),
            )
        database.execute("PRAGMA optimize")


initialize_database()


@app.context_processor
def inject_auth_context():
    return {
        "csrf_token": ensure_csrf_token(),
        "ai_configured": bool(os.environ.get("OPENAI_API_KEY")),
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
            customer = database.execute(
                "SELECT * FROM customers WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
        if customer and check_password_hash(customer["password_hash"], password):
            session.clear()
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
            return redirect(
                next_url if next_url.startswith("/") else url_for("storefront")
            )
        flash("Invalid email or password.", "error")
    return render_template("customer_login.html")


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
        if len(full_name) < 2:
            flash("Enter your full name.", "error")
        elif "@" not in email or len(email) > 254:
            flash("Enter a valid email address.", "error")
        elif len(password) < 12:
            flash("Password must contain at least 12 characters.", "error")
        elif password != confirm_password:
            flash("Password confirmation does not match.", "error")
        else:
            try:
                with get_db() as database:
                    cursor = database.execute(
                        "INSERT INTO customers (full_name, email, password_hash) VALUES (?, ?, ?)",
                        (full_name, email, generate_password_hash(password)),
                    )
                    customer_id = cursor.lastrowid
                log_activity("customer", customer_id, email, "register")
                flash("Account created. You can now sign in.", "success")
                return redirect(url_for("customer_login"))
            except sqlite3.IntegrityError:
                flash("An account already uses that email address.", "error")
    return render_template("customer_register.html")


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
    catalog = hide_customer_pricing(catalog)
    return render_template(
        "index.html", products=catalog, categories=CATEGORIES, partners=partners
    )


@app.route("/products")
@customer_required
def products():
    category = request.args.get("category", "All")
    query = request.args.get("q", "").lower()
    brand = request.args.get("brand", "")
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
    sql += " ORDER BY id DESC"
    with get_db() as database:
        results = rows_to_dicts(database.execute(sql, parameters))
        brands = [
            row[0]
            for row in database.execute(
                "SELECT DISTINCT brand FROM products ORDER BY brand"
            )
        ]
    add_manufacturer_logos(results)
    results = hide_customer_pricing(results)
    return render_template(
        "products.html",
        products=results,
        category=category,
        query=request.args.get("q", ""),
        categories=CATEGORIES,
        brands=brands,
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
        item = hide_customer_pricing([item])[0]
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
    return jsonify(hide_customer_pricing(catalog))


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


def call_ai_solution_advisor(history, catalog):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "The AI advisor is not configured yet. Add OPENAI_API_KEY to the server environment."
        )
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError(
            "The OpenAI Python package is not installed. Install the project requirements."
        ) from error

    instructions = """You are VTIC's enterprise IT solution discovery assistant.
Ask concise clarifying questions when requirements are incomplete. Once enough
information exists, provide exactly three materially different options named
Essential, Recommended, and Enterprise. Recommend ONLY product_id values from
the supplied VTIC catalog. Never invent products, prices, stock, delivery dates,
compatibility guarantees, or certifications. Never reveal or estimate prices.
Explain that every design requires VTIC engineering and commercial review.
Use realistic quantities based on stated sites, users, ports, cameras and scope.
Mark enhancements that are not required as optional."""
    model = os.environ.get("OPENAI_MODEL", "gpt-5.6-terra")
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=[
            {
                "role": "developer",
                "content": "Available VTIC catalog (prices intentionally omitted):\n"
                + json.dumps(catalog, ensure_ascii=False),
            },
            *history,
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "vtic_solution_advisor",
                "strict": True,
                "schema": AI_ADVISOR_SCHEMA,
            }
        },
        store=False,
    )
    return json.loads(response.output_text)


def call_storefront_product_chat(history, catalog, product=None):
    """Answer catalog questions without sending confidential pricing to the model."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "The AI assistant is not configured yet. Add OPENAI_API_KEY to the server environment."
        )
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError(
            "The OpenAI Python package is not installed. Install the project requirements."
        ) from error

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
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-5.6-terra"),
        instructions=instructions,
        input=[
            {
                "role": "developer",
                "content": focus
                + "\nAvailable VTIC catalog (confidential fields omitted):\n"
                + json.dumps(catalog, ensure_ascii=False),
            },
            *history,
        ],
        store=False,
    )
    return response.output_text.strip()


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
        ai_configured=bool(os.environ.get("OPENAI_API_KEY")),
        anam_agent_id=os.environ.get(
            "ANAM_AGENT_ID", "854eaac4-bd3b-40f6-9f0c-26970e0a7c19"
        ).strip(),
    )


@app.route("/api/ai/advisor", methods=["POST"])
@customer_required
def ai_advisor_message():
    if not session.get("customer_id"):
        return jsonify(error="A customer account is required to use the advisor."), 403
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
                "SELECT * FROM ai_conversations WHERE id = ? AND customer_id = ?",
                (conversation_id, session["customer_id"]),
            ).fetchone()
            if not conversation:
                return jsonify(error="Conversation not found."), 404
        else:
            cursor = database.execute(
                "INSERT INTO ai_conversations (customer_id, title) VALUES (?, ?)",
                (session["customer_id"], message[:100]),
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
        "customer", session["customer_id"], session.get("customer_email", "customer"),
        "ai_advisor_message", f"Conversation #{conversation_id}"
    )
    return jsonify(conversation_id=conversation_id, **advice)


@app.route("/api/ai/product-chat", methods=["POST"])
@customer_required
def storefront_product_chat():
    if not session.get("customer_id"):
        return jsonify(error="A customer account is required to use the assistant."), 403

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
                "SELECT id FROM ai_conversations WHERE id = ? AND customer_id = ?",
                (conversation_id, session["customer_id"]),
            ).fetchone()
            if not conversation:
                return jsonify(error="Conversation not found."), 404
        else:
            title = f"Product chat: {product['name']}" if product else message[:100]
            cursor = database.execute(
                "INSERT INTO ai_conversations (customer_id, title) VALUES (?, ?)",
                (session["customer_id"], title),
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
        "customer",
        session["customer_id"],
        session.get("customer_email", "customer"),
        "storefront_ai_chat",
        f"Conversation #{conversation_id}"
        + (f", product #{product_id}" if product else ""),
    )
    return jsonify(answer=answer, conversation_id=conversation_id)


@app.route("/api/review-requests", methods=["POST"])
@customer_required
def create_review_request():
    if not session.get("customer_id"):
        abort(403)
    payload = request.get_json(silent=True) or {}
    if not secrets.compare_digest(
        session.get("csrf_token", ""), request.headers.get("X-CSRF-Token", "")
    ):
        abort(400, "Invalid security token")
    submitted_items = payload.get("items")
    notes = str(payload.get("notes", "")).strip()[:2000]
    ai_solution_option_id = payload.get("ai_solution_option_id")
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
        if ai_solution_option_id is not None:
            try:
                ai_solution_option_id = int(ai_solution_option_id)
            except (TypeError, ValueError):
                return jsonify(error="Invalid AI solution selection."), 400
            owned_option = database.execute(
                """SELECT o.id FROM ai_solution_options o
                   JOIN ai_conversations c ON c.id = o.conversation_id
                   WHERE o.id = ? AND c.customer_id = ?""",
                (ai_solution_option_id, session["customer_id"]),
            ).fetchone()
            if not owned_option:
                return jsonify(error="AI solution selection not found."), 400
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
               (customer_id, customer_name, customer_email, ai_solution_option_id, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                session["customer_id"],
                session.get("customer_name", "Customer"),
                session.get("customer_email", ""),
                ai_solution_option_id,
                notes,
            ),
        )
        request_id = cursor.lastrowid
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
            admin = database.execute(
                "SELECT * FROM admins WHERE username = ?", (username,)
            ).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            session["admin_role"] = admin["role"]
            session["csrf_token"] = secrets.token_hex(24)
            log_activity("admin", admin["id"], admin["username"], "admin_login")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid username or password.", "error")
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
        elif new_password and len(new_password) < 12:
            flash("The new password must contain at least 12 characters.", "error")
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
            except sqlite3.IntegrityError:
                flash("That username is already in use.", "error")

    return render_template("admin_account.html", admin=dict(admin))


@app.route("/admin/accounts")
@superadmin_required
def admin_accounts():
    with get_db() as database:
        administrators = rows_to_dicts(
            database.execute(
                """SELECT id, username, role, created_at
                   FROM admins ORDER BY username COLLATE NOCASE"""
            )
        )
        customers = rows_to_dicts(
            database.execute(
                """SELECT id, full_name, email, created_at, last_login_at
                   FROM customers ORDER BY full_name COLLATE NOCASE"""
            )
        )
    return render_template(
        "admin_accounts.html",
        administrators=administrators,
        customers=customers,
    )


@app.route("/admin/accounts/new/<account_type>", methods=["GET", "POST"])
@superadmin_required
def admin_account_create(account_type):
    if account_type not in {"admin", "customer"}:
        abort(404)

    if request.method == "POST":
        validate_csrf()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(password) < 12:
            flash("Password must contain at least 12 characters.", "error")
        elif password != confirm_password:
            flash("Password confirmation does not match.", "error")
        else:
            try:
                with get_db() as database:
                    if account_type == "admin":
                        username = request.form.get("username", "").strip()
                        role = request.form.get("role", "admin")
                        if len(username) < 3:
                            raise ValueError("Username must contain at least 3 characters.")
                        if role not in {"admin", "superadmin"}:
                            raise ValueError("Select a valid administrator role.")
                        cursor = database.execute(
                            """INSERT INTO admins (username, password_hash, role)
                               VALUES (?, ?, ?)""",
                            (username, generate_password_hash(password), role),
                        )
                        account_label = username
                    else:
                        full_name = request.form.get("full_name", "").strip()
                        email = request.form.get("email", "").strip().lower()
                        if len(full_name) < 2:
                            raise ValueError("Enter the customer's full name.")
                        if "@" not in email or len(email) > 254:
                            raise ValueError("Enter a valid customer email address.")
                        cursor = database.execute(
                            """INSERT INTO customers (full_name, email, password_hash)
                               VALUES (?, ?, ?)""",
                            (full_name, email, generate_password_hash(password)),
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
            except sqlite3.IntegrityError:
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
        abort(404)
    account = dict(row)

    if request.method == "POST":
        validate_csrf()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if password and len(password) < 12:
            flash("A replacement password must contain at least 12 characters.", "error")
        elif password != confirm_password:
            flash("Password confirmation does not match.", "error")
        else:
            try:
                with get_db() as database:
                    if account_type == "admin":
                        username = request.form.get("username", "").strip()
                        role = request.form.get("role", "admin")
                        if len(username) < 3:
                            raise ValueError("Username must contain at least 3 characters.")
                        if role not in {"admin", "superadmin"}:
                            raise ValueError("Select a valid administrator role.")
                        if account_id == session["admin_id"] and role != "superadmin":
                            raise ValueError(
                                "You cannot remove superadmin access from your active account."
                            )
                        fields = ["username = ?", "role = ?"]
                        values = [username, role]
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
            except sqlite3.IntegrityError:
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
                "SELECT * FROM activity_logs ORDER BY id DESC LIMIT 500"
            )
        )
    return render_template("admin_activity.html", logs=logs)


@app.route("/admin/review-requests")
@login_required
def admin_review_requests():
    with get_db() as database:
        requests_list = rows_to_dicts(
            database.execute(
                """SELECT r.*, o.name AS ai_option_name,
                          c.requirements_summary AS ai_requirements_summary,
                          COUNT(i.id) AS line_count,
                          COALESCE(SUM(i.quantity), 0) AS item_count,
                          SUM(CASE WHEN i.unit_price IS NOT NULL
                                   THEN i.unit_price * i.quantity END) AS total_price,
                          SUM(CASE WHEN i.unit_price IS NULL THEN 1 ELSE 0 END) AS unpriced_count
                   FROM review_requests r
                   LEFT JOIN review_request_items i ON i.request_id = r.id
                   LEFT JOIN ai_solution_options o ON o.id = r.ai_solution_option_id
                   LEFT JOIN ai_conversations c ON c.id = o.conversation_id
                   GROUP BY r.id
                   ORDER BY r.id DESC"""
            )
        )
        items = rows_to_dicts(
            database.execute(
                "SELECT * FROM review_request_items ORDER BY request_id DESC, id"
            )
        )
    items_by_request = {}
    for item in items:
        items_by_request.setdefault(item["request_id"], []).append(item)
    return render_template(
        "admin_review_requests.html",
        requests=requests_list,
        items_by_request=items_by_request,
    )


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
        categories=CATEGORIES[1:],
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
                categories=CATEGORIES[1:],
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
        categories=CATEGORIES[1:],
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
                categories=CATEGORIES[1:],
                manufacturers=get_manufacturers(),
            )
        if not manufacturer_exists(values[0]):
            flash("Select a manufacturer from the list.", "error")
            return render_template(
                "admin_product_form.html",
                product=dict(row),
                categories=CATEGORIES[1:],
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
        categories=CATEGORIES[1:],
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
            except sqlite3.IntegrityError:
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
            except sqlite3.IntegrityError:
                flash("Another manufacturer already uses that name.", "error")
    return render_manufacturer_workspace(row)


@app.route("/admin/manufacturers/products-template.csv")
@login_required
def admin_manufacturer_csv_template():
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["name", "category", "price", "description", "source", "color", "image_url"]
    )
    writer.writerow(
        [
            "Example Managed Switch", "Switches", "24990.00",
            "24-port managed enterprise switch.", "Partner quotation",
            "#e8f0ff", "https://example.com/product-image.jpg",
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
        existing_names = {
            row[0].casefold()
            for row in database.execute(
                "SELECT name FROM products WHERE brand = ? COLLATE NOCASE",
                (manufacturer["name"],),
            )
        }
    try:
        content = upload.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("The CSV must be UTF-8 encoded.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    reader = csv.DictReader(io.StringIO(content))
    required_headers = {"name", "category", "description"}
    headers = {header.strip().lower() for header in (reader.fieldnames or []) if header}
    if not required_headers.issubset(headers):
        flash("CSV headers must include name, category, and description.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))

    records = []
    errors = []
    imported_names = set()
    for row_number, raw_row in enumerate(reader, start=2):
        if row_number > 1001:
            errors.append("The file exceeds the 1,000-product import limit.")
            break
        row = {(key or "").strip().lower(): (value or "").strip() for key, value in raw_row.items()}
        if not any(row.values()):
            continue
        name = row.get("name", "")
        category = row.get("category", "")
        description = row.get("description", "")
        price_text = row.get("price", "")
        if not name:
            errors.append(f"Row {row_number}: product name is required.")
        elif name.casefold() in existing_names or name.casefold() in imported_names:
            errors.append(f"Row {row_number}: {name} already exists for this manufacturer.")
        if category not in CATEGORIES[1:]:
            errors.append(f"Row {row_number}: category '{category}' is not recognized.")
        if not description:
            errors.append(f"Row {row_number}: description is required.")
        price = None
        if price_text:
            try:
                price = float(price_text.replace(",", ""))
                if price < 0:
                    raise ValueError
            except ValueError:
                errors.append(f"Row {row_number}: price must be a positive number or blank.")
        color = row.get("color") or "#e8f0ff"
        if len(color) != 7 or not color.startswith("#"):
            errors.append(f"Row {row_number}: color must use a value such as #e8f0ff.")
        imported_names.add(name.casefold())
        records.append(
            (
                manufacturer["name"], name, category, price, description,
                row.get("source") or "Partner quotation", color,
                row.get("image_url") or None,
            )
        )
    if errors:
        preview = " ".join(errors[:8])
        if len(errors) > 8:
            preview += f" Plus {len(errors) - 8} more error(s)."
        flash(f"Nothing was imported. {preview}", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    if not records:
        flash("The CSV does not contain any product rows.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    with get_db() as database:
        database.executemany(
            """INSERT INTO products
               (brand, name, category, price, description, source, color, image_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
    log_activity(
        "admin", session["admin_id"], session["admin_username"],
        "product_csv_import", f"{manufacturer['name']}: {len(records)} products"
    )
    flash(f"Imported {len(records)} product(s) for {manufacturer['name']}.", "success")
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
    if not name or not description or category not in CATEGORIES[1:]:
        flash("Product name, valid category, and description are required.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    try:
        price = float(price_text.replace(",", "")) if price_text else None
        if price is not None and price < 0:
            raise ValueError
    except ValueError:
        flash("Price must be a positive number or left blank.", "error")
        return redirect(url_for("admin_manufacturer_edit", manufacturer_id=manufacturer_id))
    with get_db() as database:
        database.execute(
            """UPDATE products SET name = ?, category = ?, price = ?,
               description = ?, source = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (name, category, price, description, source, product_id),
        )
    log_activity(
        "admin", session["admin_id"], session["admin_username"],
        "product_quick_update", f"Product #{product_id}: {name}"
    )
    flash(f"{name} was updated.", "success")
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
