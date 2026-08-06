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
- Password: `ChangeMe-VTIC-2026!`

Before production, set `VTIC_ADMIN_USERNAME`, `VTIC_ADMIN_PASSWORD`, and
`VTIC_SECRET_KEY` environment variables. Customers do not need an account.
