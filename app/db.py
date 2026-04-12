import sqlite3
from flask import current_app

# ---------------- Database Setup ----------------
def init_db():
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    cur = conn.cursor()

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

    # helpful index
    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)")

    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn