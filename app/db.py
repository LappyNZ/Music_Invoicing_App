import sqlite3
from datetime import datetime, timezone

from flask import current_app

from utils import DATETIME_FORMAT, parse_datetime

# ---------------- Database Setup ----------------
# Runs on every start, often in several gunicorn workers at once. BEGIN IMMEDIATE takes the
# write lock up front, so they take turns instead of racing to add the same column.
def init_db():
    conn = sqlite3.connect(current_app.config["DB_PATH"], timeout=30, isolation_level=None)
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        _create_and_migrate(cur)
        cur.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            cur.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _create_and_migrate(cur):
    # --- base tables ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        parent TEXT,
        phone TEXT,
        school TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        lesson_time TEXT NOT NULL,
        duration INTEGER NOT NULL,
        rate REAL NOT NULL,
        FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        start_date TEXT,
        end_date TEXT,
        total REAL,
        emailed_at TEXT,
        emailed_to TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --- migrations: students ---
    cur.execute("PRAGMA table_info(students)")
    s_cols = [r[1] for r in cur.fetchall()]
    if "school" not in s_cols:
        cur.execute("ALTER TABLE students ADD COLUMN school TEXT")
    if "active" not in s_cols:
        cur.execute("ALTER TABLE students ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    if "archived_at" not in s_cols:
        cur.execute("ALTER TABLE students ADD COLUMN archived_at TEXT")

    # --- migrations: invoices ---
    cur.execute("PRAGMA table_info(invoices)")
    i_cols = [r[1] for r in cur.fetchall()]
    if "status" not in i_cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN status TEXT DEFAULT 'draft'")
    if "paid_at" not in i_cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN paid_at TEXT")
    if "paid_amount" not in i_cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN paid_amount REAL")
    if "paid_ref" not in i_cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN paid_ref TEXT")
    if "voided_at" not in i_cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN voided_at TEXT")
    if "void_reason" not in i_cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN void_reason TEXT")
    if "invoice_number" not in i_cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN invoice_number TEXT")
    if "pdf_filename" not in i_cols:
        cur.execute("ALTER TABLE invoices ADD COLUMN pdf_filename TEXT")

    # helpful index
    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number)")

    # --- one-off data fixes, each applied once and recorded in the database's user_version ---
    done = cur.execute("PRAGMA user_version").fetchone()[0]
    for number, fix in enumerate(DATA_FIXES, start=1):
        if number > done:
            fix(cur)
            cur.execute(f"PRAGMA user_version = {number}")


def _store_invoice_numbers(cur):
    # Numbers used to be worked out from created_at every time; keep the ones already issued.
    cur.execute("""UPDATE invoices
                      SET invoice_number = 'INV-' || COALESCE(substr(created_at, 1, 4), strftime('%Y', 'now'))
                                           || '-' || printf('%04d', id)
                    WHERE invoice_number IS NULL""")
    cur.execute("UPDATE invoices SET pdf_filename = invoice_number || '.pdf' WHERE pdf_filename IS NULL")


def _tidy_paid_at(cur):
    # Store paid_at as local 'YYYY-MM-DD HH:MM'. Left blank, it used to be filled from SQLite's
    # clock, which is UTC; the form's own values are local but have a 'T' in the middle.
    for invoice_id, utc in cur.execute(
            "SELECT id, paid_at FROM invoices WHERE paid_at GLOB '????-??-?? ??:??:??'").fetchall():
        local = datetime.fromisoformat(utc).replace(tzinfo=timezone.utc).astimezone()
        cur.execute("UPDATE invoices SET paid_at=? WHERE id=?", (local.strftime("%Y-%m-%d %H:%M"), invoice_id))
    cur.execute("UPDATE invoices SET paid_at = substr(replace(paid_at, 'T', ' '), 1, 16) "
                "WHERE paid_at GLOB '????-??-??T??:??*'")


def _fix_unreadable_lesson_times(cur):
    # Times typed into the old free-text edit box. A copy of an existing lesson is removed;
    # anything that can't be read at all is left for a person (the Lessons page flags it).
    for lesson_id, student_id, text, duration, rate in cur.execute(
            "SELECT id, student_id, lesson_time, duration, rate FROM lessons").fetchall():
        when = parse_datetime(text)
        if when is None or text == when.strftime(DATETIME_FORMAT):
            continue
        fixed = when.strftime(DATETIME_FORMAT)
        duplicate = cur.execute("""SELECT 1 FROM lessons WHERE student_id=? AND lesson_time=?
                                     AND duration=? AND rate=? AND id<>?""",
                                (student_id, fixed, duration, rate, lesson_id)).fetchone()
        if duplicate:
            cur.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
        else:
            cur.execute("UPDATE lessons SET lesson_time=? WHERE id=?", (fixed, lesson_id))


def _void_replaced_zero_payments(cur):
    # Before Void existed, a wrong invoice was retired by marking it paid at $0 once a replacement
    # for the same student and period had been made. Other $0 payments (a waived fee?) stay as they are.
    cur.execute("""UPDATE invoices
                      SET status = 'void',
                          voided_at = paid_at,
                          void_reason = COALESCE(NULLIF(TRIM(paid_ref), ''), 'Replaced by a later invoice')
                    WHERE status = 'paid' AND paid_amount = 0 AND total > 0
                      AND EXISTS (SELECT 1 FROM invoices AS later
                                   WHERE later.student_id = invoices.student_id
                                     AND later.start_date = invoices.start_date
                                     AND later.end_date = invoices.end_date
                                     AND later.id > invoices.id)""")


# In order. Add new fixes at the end; never change or reorder the ones already released.
DATA_FIXES = [
    _store_invoice_numbers,
    _tidy_paid_at,
    _fix_unreadable_lesson_times,
    _void_replaced_zero_payments,
]

def get_db():
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn