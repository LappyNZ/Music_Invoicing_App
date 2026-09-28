## 🎻 Music Invoice App

A Flask-based invoicing web application for managing private music students, lessons, and billing.

Designed for simplicity, safety, and maintainability, with a clean UI and a Docker-based deployment workflow.

## ✨ Features

The app is organised around the school term:

* **Home** says what to do next: check the register, make the invoices, send them, get the next term ready
* **Register:** each term's lessons week by week (or the whole term as a grid). Every lesson starts as
  *Had lesson*; mark only the ones that were *Cancelled* (no charge) or *Missed* (still charged), and add
  extra or makeup lessons
* **Start a term:** dates, days off (public holidays are suggested) and each student's regular lesson and
  hourly rate, which fills the register for the whole term
* **Invoices made from the register** in one go, one per student or per family, kept line by line.
  Add items (exam fees, discounts), change the email wording for one invoice, email yourself a copy first,
  then send them all with a progress window
* PDFs with the logo, "Prompt payment is appreciated", and the payment Reference (`INV26-0042`) and Particulars
* **After sending:** payments (part or full), *Correct and resend* (the invoice keeps its number and is
  marked as corrected), move what's owing to the next invoice, write off, void, and undo
* Students who stop are archived, keeping their history
* Email via the Gmail API (OAuth), with a safe development mode that blocks or redirects email
* Docker-based dev and production environments

## 🏗️ Project Structure

music-invoice/
├─ app/
│  ├─ app.py              # Flask app entry point
│  ├─ config.py           # Central config (env-driven)
│  ├─ db.py               # DB connection, set-up and upgrades
│  ├─ gmail_auth.py       # Connects the app to Gmail (python -m gmail_auth)
│  ├─ terms.py            # Terms, weeks and which lessons fall in them
│  ├─ billing.py          # Invoices from the register: drafts, lines, sending, payments, corrections
│  ├─ utils.py            # Shared helpers (money in cents, dates)
│  ├─ routes/             # Blueprints
│  │  ├─ home.py          # Home: the next step
│  │  ├─ register.py      # Register and Start a term
│  │  ├─ invoices.py
│  │  ├─ students.py
│  │  └─ lessons.py       # List of all lessons
│  ├─ services/           # Business logic
│  │  ├─ email_service.py
│  │  ├─ invoice_service.py
│  │  └─ pdf_service.py
│  ├─ tools/              # One-off maintenance, e.g. restore_deleted_students.py
│  ├─ templates/
│  └─ static/
│
├─ deploy/unraid/         # Server compose file, scripts and runbook
├─ scripts/reset_dev_db.py  # Fills data-dev/ with made-up sample data
├─ tests/                 # pytest
│
├─ docker/
│  ├─ Dockerfile
│  ├─ docker-compose.dev.yml
│  └─ docker-compose.prod.yml
│
├─ data/                  # Production DB + PDFs (NOT in git)
├─ data-dev/              # Dev DB + PDFs (NOT in git)
├─ secrets/               # OAuth credentials (NOT in git)
│
├─ .env.dev
├─ .env.prod
├─ .env.example           # Template only (safe)
├─ .gitignore
└─ README.md

## ⚙️ Environment Configuration

All configuration is managed via environment variables.

.env.example → .env.dev

and update values as needed.

## Key variables

# App
APP_ENV=development
FLASK_DEBUG=1
FLASK_SECRET_KEY=change-me

# Paths
DB_PATH=/data-dev/music_school_dev.db
INVOICE_PDF_DIR=/data-dev/invoices_pdfs

# Email safety
EMAIL_ENABLED=0
EMAIL_REDIRECT_TO=

# Gmail OAuth
SECRETS_DIR=/secrets
GOOGLE_OAUTH_CREDENTIALS=/secrets/credentials.json
GOOGLE_OAUTH_TOKEN=/secrets/token.json
# Only appears in the address Google sends the browser back to when connecting Gmail
OAUTH_PORT=8090

# Pretend it's another day (e.g. TODAY=2026-09-28) for a demonstration; leave empty
TODAY=

# Business details (used in invoices)
SENDER_EMAIL=your-email@example.com
SENDER_NAME=Your Name
# Printed on the PDF next to the logo; leave empty to show just the logo
BUSINESS_NAME=
BUSINESS_ADDRESS_LINE1=123 Example Street
BUSINESS_ADDRESS_LINE2=Example City
BUSINESS_PHONE=000 000 0000
BUSINESS_MOBILE=000 000 0000
BANK_ACCOUNT=00-0000-0000000-000

## 🚀 Local Development (Docker)

Start dev environment

docker compose -f docker/docker-compose.dev.yml up --build

App will be available at:

http://localhost:8086

Stop

docker compose -f docker/docker-compose.dev.yml down

Sample data (made-up students and a finished Term 3 2026 with its invoices; replaces what's in data-dev/)

python scripts/reset_dev_db.py

Connect Gmail (only needed to send real email; see EMAIL_ENABLED below)

docker exec -it music-invoice-dev python -m gmail_auth

## 🛡️ Email Safety (Important)

In development:

EMAIL_ENABLED=0

This ensures:

* No real emails are sent
* UI reports “Not sent”
* Logs show blocked emails

Optional:

EMAIL_REDIRECT_TO=your@email.com

→ all emails redirected to one address for testing

## 🧾 Production Deployment (Unraid / Docker)

The Unraid server runs the image that GitHub Actions publishes from `main`
(`ghcr.io/lappynz/music_invoicing_app`), with its data in `/mnt/user/appdata/music-invoice`.

See **[deploy/unraid/README.md](deploy/unraid/README.md)** for updating, rolling back, nightly backups and
restoring from a backup.

# Important: Data Persistence

The following folders are mounted and must be preserved:

* data/ → SQLite database + PDFs
* secrets/ → OAuth credentials/tokens

These are not part of the container image and will survive updates.

## 🔄 Updating the App

Recommended workflow:

1. Develop and test locally (`pytest`)
2. Commit on a branch and open a pull request; GitHub runs the tests
3. Merge into `main`; GitHub publishes a new image once the tests pass
4. On the server: `bash /mnt/user/appdata/music-invoice/scripts/update.sh`

Your data is safe because it lives outside the container, and `update.sh` takes a backup first.

## 🧪 Development Workflow

Suggested VS Code tasks:

* Dev: up
* Dev: down
* Dev: logs
* Dev: restart

Use a Python venv locally for linting/debugging, but Docker is the source of truth for runtime.

Run the tests before committing:

pip install -r requirements-dev.txt
pytest

## 🔐 Security Notes

The following are never committed to git:

* .env.dev, .env.prod
* data/, data-dev/
* secrets/
* generated PDFs

Only .env.example is tracked.

## 📦 Tech Stack

* Flask
* SQLite
* ReportLab (PDF generation)
* Gmail API (OAuth)
* Bootstrap 5 (UI)
* Docker / Docker Compose
* Unraid (deployment)

## 🧭 Future Improvements

See [docs/review-and-roadmap.md](docs/review-and-roadmap.md) for the full plan. In short:

* Instruments and rentals
* Importing the bank statement to tick off payments
* Card payments

## ⚠️ Disclaimer

This is a personal invoicing tool. Use at your own risk and ensure:

* regular backups of data/
* OAuth credentials are kept secure
* email sending is tested before enabling in production

## 👍 Summary

* Clean modular Flask architecture (Blueprints + services)
* Safe dev environment (no accidental emails)
* Docker-first workflow
* Persistent data model for easy updates