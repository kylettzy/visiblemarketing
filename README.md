# Cartly e-commerce demo

A responsive Lazada-inspired marketplace built with Python/Flask, HTML, page-specific CSS, and vanilla JavaScript.

## Run

```powershell
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

## Admin catalog

Open http://127.0.0.1:5000/admin/login.

Development credentials:

- Username: `admin`
- Password: `visibletechintlcorp`

Before production, set `VTIC_ADMIN_USERNAME`, `VTIC_ADMIN_PASSWORD`, and
`VTIC_SECRET_KEY` environment variables. Customers do not need an account.
# Deploying on Vercel

The project is configured as a zero-configuration Flask application for
Vercel's Python runtime.

Set these Environment Variables in **Vercel → Project → Settings → Environment
Variables** before deploying:

- `VTIC_SECRET_KEY`: a long random value (required for secure admin sessions)
- `VTIC_ADMIN_USERNAME`: the initial admin username
- `VTIC_ADMIN_PASSWORD`: the initial admin password (use at least 12 characters)

Deploy from the project directory:

```powershell
npx vercel@latest
npx vercel@latest --prod
```

Vercel Functions have a read-only filesystem. This application uses `/tmp` on
Vercel so it can start successfully, but `/tmp` is temporary: database changes
and uploaded images can disappear after a cold start or be different between
function instances. For a production storefront, migrate SQLite to a managed
Postgres database and uploaded images to durable object storage such as Vercel
Blob before relying on the admin panel for permanent data.
