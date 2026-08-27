# VTIC ICT Solutions Consultation and Proposal Management System

A responsive consultation and project-quotation platform built with
Python/Flask, HTML, page-specific CSS, SQLite, and vanilla JavaScript. Customers
explore the solutions catalog, build a review list, consult with VTIC, and track
requests through pricing, technical validation, BOM preparation, proposal, and
final approval. The platform does not provide direct online checkout or payment.

## Quick start

Open PowerShell and run:

```powershell
cd C:\Users\VTIC-CTO\Desktop\solution-checker
py -m pip install -r requirements.txt
py -m flask --app app run --host 0.0.0.0 --port 5000
```

Then open http://127.0.0.1:5000 in a browser. Keep the terminal open while
using the website. Press `Ctrl+C` in the terminal to stop the server.

If the `py` command is unavailable, replace it with `python`.

## Run locally on Windows

### 1. Open PowerShell in the project folder

```powershell
cd C:\Users\VTIC-CTO\Desktop\solution-checker
```

### 2. Create a virtual environment (first run only)

```powershell
python -m venv .venv
```

### 3. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can skip this step and use the `.venv`
Python executable directly in the following commands.

### 4. Install the dependencies (first run, or after requirements change)

```powershell
python -m pip install -r requirements.txt
```

Without activating the virtual environment, run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Configure local environment values

Open the project `.env` file and paste the Gemini API key after the equals sign:

```env
GEMINI_API_KEY=your-secret-key
GEMINI_MODEL=gemini-3.6-flash
```

The application automatically loads `.env` at startup. The file is excluded
from Git and must never be uploaded or shared. `.env.example` documents the
required variable names without containing secret values.

### 5. Start the website

```powershell
python -m flask --app app run --host 0.0.0.0 --port 5000
```

Without activating the virtual environment, run:

```powershell
.\.venv\Scripts\python.exe -m flask --app app run --host 0.0.0.0 --port 5000
```

### 6. Open the website

- Storefront: http://127.0.0.1:5000/
- Product catalog: http://127.0.0.1:5000/products
- Admin login: http://127.0.0.1:5000/admin/login

Keep the PowerShell window open while using the website. Press `Ctrl+C` in
that window to stop the server.

## Customer storefront access

The storefront is private. A customer must create an account before viewing
products, product details, the cart, or the catalog API.

- Register: http://127.0.0.1:5000/register
- Customer login: http://127.0.0.1:5000/login

Customer passwords must contain at least 12 characters. Customers can create
their own accounts; no admin approval is currently required.

### Private pricing and review cart

Customers do not receive product prices in storefront pages, cart data, or the
catalog API. They can add any available products, adjust quantities, enter
project notes, and select **Submit for review** when their list is complete.

The server validates the submitted product IDs and stores the authoritative
internal price at submission time. Administrators and superadmins can review
the customer's selection, quantities, notes, internal unit prices, and
calculated total at:

- http://127.0.0.1:5000/admin/review-requests

When an administrator previews any storefront page, an **Admin** dropdown is
shown in the header. It links directly to product management, add product,
manufacturers, review requests, admin settings, and (for superadmins) activity
logs.

The public partner section only lists manufacturers that currently have one or
more products. Manufacturers with no products remain visible in the admin
manufacturer page and automatically appear publicly after their first product
is assigned.

### Manufacturer product workspace and CSV import

Select **Edit** beside a manufacturer to view every product assigned to it.
Common fields can be updated using the expandable quick-edit rows; use **Open
full editor** to change product pictures, image URLs, or card styling.

The same workspace supports importing as many as 1,000 products from a UTF-8
CSV. Download the provided template from the page. Required columns are:

```text
name,category,description
```

Optional columns are:

```text
price,source,color,image_url
```

The manufacturer is taken from the workspace and cannot be overridden by the
CSV. The complete file is validated before insertion; if one row is invalid,
no rows are imported.

## AI Solution Advisor

Signed-in customers can open:

- http://127.0.0.1:5000/solution-advisor

The advisor collects project requirements, asks follow-up questions, and can
return Essential, Recommended, and Enterprise options using only products that
exist in the VTIC database. A selected option can be added to the review cart.
Admins see the selected AI option and requirements summary with the confidential
internal prices in Review Requests.

Every storefront page also includes a fixed **Ask VTIC** assistant in the
bottom-right corner, so it stays available while the customer scrolls. On a
product detail page, the assistant automatically receives that product's safe
catalog details and offers an **Add this product to cart** shortcut. Prices are
never included in the browser request or the AI context. General storefront
questions can be continued in the full Solution Advisor for multi-product
planning.

Install the current requirements and configure the server-side API key:

```powershell
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-google-ai-studio-key"
$env:GEMINI_MODEL = "gemini-3.6-flash"
python app.py
```

Never place `GEMINI_API_KEY` in HTML, JavaScript, Git, or a public Vercel
environment variable. On Vercel, add it in **Project → Settings → Environment
Variables** for the server runtime. `GEMINI_MODEL` is optional and defaults to
`gemini-3.6-flash`.

### Anam AI representative

The Solution Advisor page includes an optional inline Anam video and voice
representative. Create and publish a VTIC persona in Anam Lab, enable text
input, and add both your development and production origins to the persona's
Widget **Allowed domains** list. For local development, allow:

```text
http://127.0.0.1:5000
http://localhost:5000
```

Set the published persona ID before starting Flask:

```powershell
$env:ANAM_AGENT_ID = "your-published-anam-persona-id"
python app.py
```

The project currently defaults to the published VTIC Anam persona
`854eaac4-bd3b-40f6-9f0c-26970e0a7c19`. Set `ANAM_AGENT_ID` only when you want
to replace it with another persona without changing the application code.

On Vercel, add `ANAM_AGENT_ID` under **Project → Settings → Environment
Variables**. The ID is used by Anam's domain-authenticated web widget; do not
put an Anam API key in the HTML or browser JavaScript. Production voice and
video access requires HTTPS and customer microphone permission.

## Admin catalog and activity logs

Development credentials:

- Username: `admin`
- Password: `visibletechintlcorp`

The initial administrator is assigned the `superadmin` role. Only a signed-in
superadmin can open http://127.0.0.1:5000/admin/activity. The audit trail records
customer registration/login/logout, administrator login/logout, credential
updates, and product/manufacturer changes.

Superadmins can manage customer and administrator accounts at
http://127.0.0.1:5000/admin/accounts. They can create accounts, update customer
names and emails, assign administrator roles, and issue replacement passwords.
Regular administrators cannot access this workspace.

Before production, set `VTIC_ADMIN_USERNAME`, `VTIC_ADMIN_PASSWORD`, and
`VTIC_SECRET_KEY` environment variables. Customers create their own storefront
accounts through the registration page.

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
