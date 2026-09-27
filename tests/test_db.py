import multiprocessing
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from db import init_db

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# Structure of the production database as of September 2026 (no data).
LIVE_SCHEMA_2026_09 = """
CREATE TABLE students ( id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL, parent TEXT, phone TEXT , school TEXT);
CREATE TABLE lessons ( id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL, lesson_time TEXT NOT NULL, duration INTEGER NOT NULL, rate REAL NOT NULL, FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE );
CREATE TABLE invoices ( id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, start_date TEXT, end_date TEXT, total REAL, emailed_at TEXT, emailed_to TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP , status TEXT DEFAULT 'draft', paid_at TEXT, paid_amount REAL, paid_ref TEXT);
CREATE INDEX idx_students_school ON students(school);
CREATE INDEX idx_invoices_status ON invoices(status);
"""


def make_live_shaped_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(LIVE_SCHEMA_2026_09)
    conn.execute("INSERT INTO students (name, email) VALUES ('Alice', 'a@example.com')")
    conn.execute("INSERT INTO invoices (student_id, total, status) VALUES (1, 300, 'paid')")
    conn.commit()
    conn.close()


def columns(path, table):
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return cols


def test_creates_all_tables_on_a_fresh_database(app):
    path = app.config["DB_PATH"]
    for table in ("students", "lessons", "invoices"):
        assert columns(path, table)
    assert {"status", "voided_at", "void_reason"} <= set(columns(path, "invoices"))


def test_upgrades_the_live_database_without_losing_data(app, tmp_path):
    path = str(tmp_path / "live.db")
    make_live_shaped_db(path)
    app.config["DB_PATH"] = path
    with app.app_context():
        init_db()
        init_db()  # running again is harmless

    cols = columns(path, "invoices")
    assert cols.count("voided_at") == 1 and cols.count("void_reason") == 1
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT total, status FROM invoices").fetchall() == [(300.0, "paid")]
    conn.close()


def _init_db_in_child(db_path, barrier, results):
    from app import app as flask_app
    flask_app.config["DB_PATH"] = db_path
    barrier.wait()
    try:
        with flask_app.app_context():
            init_db()
        results.put("ok")
    except Exception as exc:  # reported back to the test
        results.put(repr(exc))


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork; runs in CI on Linux")
def test_workers_starting_together_do_not_collide(tmp_path):
    # gunicorn starts several workers at once, and each one runs init_db.
    path = str(tmp_path / "live.db")
    make_live_shaped_db(path)
    ctx = multiprocessing.get_context("fork")
    workers = 6
    barrier, results = ctx.Barrier(workers), ctx.Queue()
    procs = [ctx.Process(target=_init_db_in_child, args=(path, barrier, results)) for _ in range(workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)

    assert sorted(results.get(timeout=5) for _ in procs) == ["ok"] * workers
    assert columns(path, "invoices").count("voided_at") == 1


def test_importing_the_app_sets_up_the_database(tmp_path):
    # start.sh relies on this to create/upgrade the database before gunicorn starts.
    path = tmp_path / "startup.db"
    env = dict(os.environ, DB_PATH=str(path), INVOICE_PDF_DIR=str(tmp_path / "pdfs"))
    subprocess.run([sys.executable, "-c", "import app"], cwd=APP_DIR, env=env, check=True)
    assert "voided_at" in columns(str(path), "invoices")
