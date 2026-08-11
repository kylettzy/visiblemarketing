import os
import secrets
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
        admin_password = os.environ.get("VTIC_ADMIN_PASSWORD", "visibletechintlcorp")
        if database.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            database.execute(
                "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                (admin_username, generate_password_hash(admin_password)),
            )
        database.execute("PRAGMA optimize")


initialize_database()


@app.route("/")
def home():
    with get_db() as database:
        catalog = rows_to_dicts(database.execute("SELECT * FROM products ORDER BY id"))
    add_manufacturer_logos(catalog)
    return render_template("index.html", products=catalog, categories=CATEGORIES)


@app.route("/products")
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
    return render_template(
        "products.html",
        products=results,
        category=category,
        query=request.args.get("q", ""),
        categories=CATEGORIES,
        brands=brands,
    )


@app.route("/product/<int:product_id>")
def product(product_id):
    with get_db() as database:
        row = database.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    item = add_manufacturer_logos([dict(row)])[0] if row else None
    return (
        (render_template("product.html", product=item), 200)
        if item
        else ("Product not found", 404)
    )


@app.route("/cart")
def cart():
    return render_template("cart.html")


@app.route("/api/products")
def api_products():
    with get_db() as database:
        catalog = rows_to_dicts(database.execute("SELECT * FROM products ORDER BY id"))
    add_manufacturer_logos(catalog)
    return jsonify(catalog)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
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
            session["csrf_token"] = secrets.token_hex(24)
            return redirect(url_for("admin_dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
@login_required
def admin_logout():
    validate_csrf()
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
                flash("Account credentials updated successfully.", "success")
                return redirect(url_for("admin_account"))
            except sqlite3.IntegrityError:
                flash("That username is already in use.", "error")

    return render_template("admin_account.html", admin=dict(admin))


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
                database.execute(
                    """INSERT INTO products
                       (brand, name, category, price, description, source, color, image_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    values,
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
        database.execute("DELETE FROM products WHERE id = ?", (product_id,))
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
            return render_template(
                "admin_manufacturer_form.html", manufacturer=dict(row)
            )
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
                flash("Manufacturer updated successfully.", "success")
                return redirect(url_for("admin_manufacturers"))
            except sqlite3.IntegrityError:
                flash("Another manufacturer already uses that name.", "error")
    return render_template("admin_manufacturer_form.html", manufacturer=dict(row))


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
            flash("Manufacturer deleted.", "success")
    return redirect(url_for("admin_manufacturers"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
