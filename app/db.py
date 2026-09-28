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

    # --- the term workflow: terms, the register, and invoices kept line by line ---
    _add_columns(cur, "students", {
        "lesson_day": "INTEGER",        # regular lesson: 1 = Monday ... 7 = Sunday
        "lesson_start": "TEXT",         # 'HH:MM'
        "lesson_minutes": "INTEGER",
        "lesson_rate": "REAL",          # per hour; students can be on different rates (e.g. subsidised)
    })
    _add_columns(cur, "lessons", {
        "status": "TEXT NOT NULL DEFAULT 'taught'",   # taught, cancelled, missed (still charged) or holiday
        "kind": "TEXT NOT NULL DEFAULT 'regular'",    # regular, or extra (makeups and one-offs)
        "note": "TEXT",
        "invoice_id": "INTEGER",                      # the invoice it's billed on; 0 = billed before invoices kept lines
    })
    _add_columns(cur, "invoices", {
        "term_id": "INTEGER",                         # set on invoices made from the register
        "revision": "INTEGER NOT NULL DEFAULT 1",
        "total_cents": "INTEGER",
        "email_subject": "TEXT",                      # own wording for this invoice's email, if changed
        "email_body": "TEXT",
        "carried_to": "INTEGER",                      # the invoice an unpaid amount was moved onto
        "write_off_reason": "TEXT",
        "one_off": "INTEGER NOT NULL DEFAULT 0",      # e.g. an exam fee on its own: lessons don't go on it
    })
    cur.execute("""
    CREATE TABLE IF NOT EXISTS terms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        started_at TEXT
    )""")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_terms_start ON terms(start_date)")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS term_holidays (
        term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (term_id, date)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS register_checks (
        term_id INTEGER NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
        week INTEGER NOT NULL,
        checked_at TEXT NOT NULL,
        PRIMARY KEY (term_id, week)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'item',           -- item (incl. discounts), or carried (owing from an earlier invoice)
        description TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        carried_invoice_id INTEGER,
        created_at TEXT NOT NULL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoice_versions (
        invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL,
        sent_at TEXT NOT NULL,
        sent_to TEXT,
        total_cents INTEGER NOT NULL,
        lines_json TEXT NOT NULL,                    -- the lines exactly as sent
        pdf_filename TEXT,
        email_subject TEXT,
        email_body TEXT,
        PRIMARY KEY (invoice_id, revision)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
        paid_on TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        reference TEXT,
        created_at TEXT NOT NULL
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS invoice_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
        at TEXT NOT NULL,
        text TEXT NOT NULL
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lessons_time ON lessons(lesson_time)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_lessons_invoice ON lessons(invoice_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_items_invoice ON invoice_items(invoice_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_invoice ON invoice_events(invoice_id)")

    # --- one-off data fixes, each applied once and recorded in the database's user_version ---
    done = cur.execute("PRAGMA user_version").fetchone()[0]
    for number, fix in enumerate(DATA_FIXES, start=1):
        if number > done:
            fix(cur)
            cur.execute(f"PRAGMA user_version = {number}")


def _add_columns(cur, table, columns):
    existing = {r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


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


# The first terms billed from the register. Later terms are added by "Start the next term".
FIRST_TERMS = [("Term 3 2026", "2026-07-20", "2026-09-25"), ("Term 4 2026", "2026-10-12", "2026-12-18")]


def _add_first_terms(cur):
    for name, start, end in FIRST_TERMS:
        cur.execute("INSERT OR IGNORE INTO terms (name, start_date, end_date) VALUES (?, ?, ?)", (name, start, end))


def _regular_lessons_from_history(cur):
    # Each student's usual lesson (day, time, length, rate), from their ten most recent lessons.
    for (student_id,) in cur.execute("SELECT id FROM students WHERE lesson_day IS NULL").fetchall():
        counts = {}
        for text, minutes, rate in cur.execute("""SELECT lesson_time, duration, rate FROM lessons WHERE student_id=?
                                                    ORDER BY lesson_time DESC LIMIT 10""", (student_id,)).fetchall():
            when = parse_datetime(text)
            if when:
                key = (when.isoweekday(), when.strftime("%H:%M"), minutes, rate)
                counts[key] = counts.get(key, 0) + 1
        if counts:
            day, start, minutes, rate = max(counts, key=counts.get)
            cur.execute("UPDATE students SET lesson_day=?, lesson_start=?, lesson_minutes=?, lesson_rate=? WHERE id=?",
                        (day, start, minutes, rate, student_id))


def _link_lessons_to_invoices(cur):
    # Invoices used to record only a period, so work out which lessons each one billed. Lessons
    # before the first register term that no invoice covers are treated as dealt with (0).
    for invoice_id, student_id, start, end in cur.execute("""
            SELECT id, student_id, start_date, end_date FROM invoices
             WHERE status IS NOT 'void' AND start_date IS NOT NULL AND end_date IS NOT NULL
             ORDER BY id""").fetchall():
        cur.execute("""UPDATE lessons SET invoice_id=? WHERE invoice_id IS NULL AND student_id=?
                         AND date(lesson_time) BETWEEN date(?) AND date(?)""", (invoice_id, student_id, start, end))
    cur.execute("UPDATE lessons SET invoice_id=0 WHERE invoice_id IS NULL AND date(lesson_time) < date(?)",
                (FIRST_TERMS[0][1],))


def _payments_from_paid_fields(cur):
    # One payment per invoice used to be kept on the invoice itself; payments now have their own table.
    now = datetime.now().strftime(DATETIME_FORMAT)
    for invoice_id, status, total, paid_at, amount, ref, created_at in cur.execute("""
            SELECT id, status, total, paid_at, paid_amount, paid_ref, created_at FROM invoices
             WHERE status IS NOT 'void' AND (paid_amount > 0 OR (status = 'paid' AND paid_amount IS NULL))""").fetchall():
        cents = round((amount if amount is not None else (total or 0)) * 100)
        if cents <= 0:
            continue
        paid_on = (paid_at or created_at or now)[:10]
        cur.execute("INSERT INTO payments (invoice_id, paid_on, amount_cents, reference, created_at) VALUES (?, ?, ?, ?, ?)",
                    (invoice_id, paid_on, cents, ref, now))


# In order. Add new fixes at the end; never change or reorder the ones already released.
DATA_FIXES = [
    _store_invoice_numbers,
    _tidy_paid_at,
    _fix_unreadable_lesson_times,
    _void_replaced_zero_payments,
    _add_first_terms,
    _regular_lessons_from_history,
    _link_lessons_to_invoices,
    _payments_from_paid_fields,
]

def get_db():
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn