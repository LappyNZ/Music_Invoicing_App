import sqlite3

# Structure of the production database as of September 2026 (no data).
LIVE_SCHEMA_2026_09 = """
CREATE TABLE students ( id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL, parent TEXT, phone TEXT , school TEXT);
CREATE TABLE lessons ( id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, lesson_time TEXT NOT NULL, duration INTEGER NOT NULL, rate REAL NOT NULL, FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE );
CREATE TABLE invoices ( id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, start_date TEXT, end_date TEXT, total REAL, emailed_at TEXT, emailed_to TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP , status TEXT DEFAULT 'draft', paid_at TEXT, paid_amount REAL, paid_ref TEXT);
CREATE INDEX idx_students_school ON students(school);
CREATE INDEX idx_invoices_status ON invoices(status);
"""


def make_live_shaped_db(path, script=""):
    """A database shaped like production, with optional extra SQL to add rows."""
    conn = sqlite3.connect(path)
    conn.executescript(LIVE_SCHEMA_2026_09 + script)
    conn.commit()
    conn.close()
