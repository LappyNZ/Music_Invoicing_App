from pathlib import Path
import sqlite3

DB_PATH = Path("data-dev/music_school_dev.db")
PDF_DIR = Path("data-dev/invoices_pdfs")

PDF_DIR.mkdir(parents=True, exist_ok=True)

if DB_PATH.exists():
    DB_PATH.unlink()

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE TABLE students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    parent TEXT,
    phone TEXT,
    school TEXT
)
""")

cur.execute("""
CREATE TABLE invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    status TEXT DEFAULT 'draft',
    paid_at TEXT,
    paid_amount REAL,
    paid_ref TEXT,
    FOREIGN KEY(student_id) REFERENCES students(id)
)
""")

cur.execute("""
INSERT INTO students (name, email, parent, phone, school)
VALUES
('Test Student', 'test@example.com', 'Test Parent', '0210000000', 'Test School')
""")

conn.commit()
conn.close()

print("Dev DB reset complete.")