## 🎻 Music Invoice App

A Flask-based invoicing web application for managing private music students, lessons, and billing.

Designed for simplicity, safety, and maintainability, with a clean UI and a Docker-based deployment workflow.

## ✨ Features

* Student management (name, email, parent, phone, school)
* Lesson tracking with filtering and repeat scheduling
* Invoice generation (PDF via ReportLab)
* Bulk email sending via Gmail API (OAuth)
* Invoice status tracking:
  * Draft → Sent → Paid
* NZ school term filtering
* Persistent filters across actions
* Safe development mode (email blocking)
* Docker-based dev and production environments

## 🏗️ Project Structure

music-invoice/
├─ app/
│  ├─ app.py              # Flask app entry point
│  ├─ config.py           # Central config (env-driven)
│  ├─ db.py               # DB connection + init
│  ├─ utils.py            # Shared helpers
│  ├─ routes/             # Blueprints
│  │  ├─ students.py
│  │  ├─ lessons.py
│  │  └─ invoices.py
│  ├─ services/           # Business logic
│  │  ├─ email_service.py
│  │  ├─ invoice_service.py
│  │  └─ pdf_service.py
│  ├─ templates/
│  └─ static/
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
OAUTH_PORT=8090

# Business details (used in invoices)
SENDER_EMAIL=your-email@example.com
SENDER_NAME=Your Name
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

Production uses:

docker compose -f docker/docker-compose.prod.yml up -d

# Important: Data Persistence

The following folders are mounted and must be preserved:

* data/ → SQLite database + PDFs
* secrets/ → OAuth credentials/tokens

These are not part of the container image and will survive updates.

## 🔄 Updating the App

Recommended workflow:

1. Develop and test locally
2. Commit changes
3. Deploy to server:

docker compose -f docker/docker-compose.prod.yml up -d --build

Your data is safe because it lives outside the container.

## 🧪 Development Workflow

Suggested VS Code tasks:

* Dev: up
* Dev: down
* Dev: logs
* Dev: restart

Use a Python venv locally for linting/debugging, but Docker is the source of truth for runtime.

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

* GitHub Container Registry (GHCR) image publishing
* Automated deployment workflow
* Improved invoice preview UX
* Better payment reconciliation tools
* Multi-teacher support

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