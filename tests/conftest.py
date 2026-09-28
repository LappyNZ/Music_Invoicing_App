import os
import tempfile
import time
from types import SimpleNamespace

import pytest

# The app reads its settings from the environment when it is first imported,
# so these must be set before `app` is imported below.
_IMPORT_DIR = tempfile.mkdtemp(prefix="music-invoice-tests-")
os.environ.update(
    APP_ENV="development",
    DB_PATH=os.path.join(_IMPORT_DIR, "import.db"),
    INVOICE_PDF_DIR=os.path.join(_IMPORT_DIR, "pdfs"),
    EMAIL_ENABLED="0",
    APP_VERSION="0123456789abcdef",
)

from app import app as flask_app  # noqa: E402
from db import get_db, init_db  # noqa: E402


@pytest.fixture
def app(tmp_path):
    """The Flask app, pointed at a fresh database and PDF folder for each test."""
    flask_app.config.update(
        TESTING=True,
        DB_PATH=str(tmp_path / "test.db"),
        INVOICE_PDF_DIR=str(tmp_path / "pdfs"),
        TODAY="",
        SENDER_EMAIL="teacher@example.com",
    )
    os.makedirs(flask_app.config["INVOICE_PDF_DIR"], exist_ok=True)
    with flask_app.app_context():
        init_db()
    return flask_app


@pytest.fixture
def new_zealand_time():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Pacific/Auckland"
    time.tzset()
    yield
    if old is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = old
    time.tzset()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    """A connection to the test database, for arranging data and checking results."""
    with app.app_context():
        conn = get_db()
        yield conn
        conn.close()


@pytest.fixture
def make_student(db):
    def _make(name="Alice Aroha", email="alice@example.com", parent="Pat Aroha"):
        cur = db.execute(
            "INSERT INTO students (name, email, parent, phone, school) VALUES (?, ?, ?, '', '')",
            (name, email, parent),
        )
        db.commit()
        return cur.lastrowid
    return _make


@pytest.fixture
def make_lesson(db):
    def _make(student_id, lesson_time="2026-07-20 15:00", duration=30, rate=60.0):
        cur = db.execute(
            "INSERT INTO lessons (student_id, lesson_time, duration, rate) VALUES (?, ?, ?, ?)",
            (student_id, lesson_time, duration, rate),
        )
        db.commit()
        return cur.lastrowid
    return _make


@pytest.fixture
def make_invoice(db):
    def _make(student_id, status="draft", total=300.0, emailed_at=None, paid_amount=None):
        cur = db.execute(
            """INSERT INTO invoices (student_id, start_date, end_date, total, emailed_at, status, paid_amount)
               VALUES (?, '2026-07-20', '2026-09-25', ?, ?, ?, ?)""",
            (student_id, total, emailed_at, status, paid_amount),
        )
        # numbered the way the upgrade numbers invoices made before numbers were stored
        db.execute("""UPDATE invoices SET invoice_number = 'INV-' || substr(created_at, 1, 4) || '-' || printf('%04d', id),
                          pdf_filename = 'INV-' || substr(created_at, 1, 4) || '-' || printf('%04d', id) || '.pdf' WHERE id=?""",
                   (cur.lastrowid,))
        db.commit()
        return cur.lastrowid
    return _make


@pytest.fixture
def today(app):
    """Sets the date the app thinks it is, e.g. today("2026-09-28")."""
    def _pin(iso):
        app.config["TODAY"] = iso
    return _pin


@pytest.fixture
def terms(db):
    """The terms the database starts with, by name: {"Term 3 2026": 1, ...}."""
    return {r["name"]: r["id"] for r in db.execute("SELECT id, name FROM terms")}


@pytest.fixture
def gmail(app, monkeypatch):
    """Stands in for Gmail: records what would be sent, or fails the way it's told to."""
    from services import invoice_service
    outbox, problem = [], {}

    def fake_send(**message):
        if "error" in problem:
            raise problem["error"]
        outbox.append(message)
        return {"status": "sent", "to": message["to_email"]}

    monkeypatch.setattr(invoice_service, "send_invoice_via_gmail", fake_send)
    return SimpleNamespace(outbox=outbox, fail_with=lambda e: problem.update(error=e))


@pytest.fixture
def term3(db):
    return db.execute("SELECT * FROM terms WHERE name='Term 3 2026'").fetchone()


@pytest.fixture
def term4(db):
    return db.execute("SELECT * FROM terms WHERE name='Term 4 2026'").fetchone()


@pytest.fixture
def student(db):
    """A student, with the email and parent the register tests expect."""
    def _make(name="Alice Aroha", email=None, parent="Pat Aroha", **regular):
        cur = db.execute("INSERT INTO students (name, email, parent, phone, school) VALUES (?, ?, ?, '', '')",
                         (name, email or name.split()[0].lower() + "@example.com", parent))
        if regular:   # lesson_day, lesson_start, lesson_minutes, lesson_rate
            db.execute(f"UPDATE students SET {', '.join(k + '=?' for k in regular)} WHERE id=?", (*regular.values(), cur.lastrowid))
        db.commit()
        return cur.lastrowid
    return _make


@pytest.fixture
def lesson(db):
    def _make(student_id, when="2026-07-20 15:30", minutes=30, rate=70, status="taught", kind="regular", note=None):
        cur = db.execute("INSERT INTO lessons (student_id, lesson_time, duration, rate, status, kind, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (student_id, when, minutes, rate, status, kind, note))
        db.commit()
        return cur.lastrowid
    return _make
