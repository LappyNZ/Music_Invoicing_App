import sqlite3

import pytest

import db
from live_schema import make_live_shaped_db

# Shaped like the production data in September 2026 (made-up people and amounts).
ROWS = """
INSERT INTO students (id, name, email, parent) VALUES
  (1, 'Alice Aroha', 'pat@example.com', 'Pat Aroha'),   -- weekly Mondays, invoiced for Term 2
  (2, 'Ben Brown', 'ben@example.com', ''),              -- no Term 2 invoice
  (3, 'Cara Chen', 'mei@example.com', 'Mei Chen'),      -- one invoice covering May to December
  (4, 'Dan Doe', 'dan@example.com', '');                -- no lessons at all

INSERT INTO lessons (student_id, lesson_time, duration, rate) VALUES
  (1, '2026-06-29 15:30', 30, 70), (1, '2026-07-10 15:30', 30, 70),
  (1, '2026-07-20 15:30', 30, 70), (1, '2026-07-27 15:30', 30, 70), (1, '2026-08-03 16:00', 45, 70),
  (2, '2026-06-30 16:00', 45, 65), (2, '2026-07-21 16:00', 45, 65),
  (3, '2026-06-30 17:00', 30, 70), (3, '2026-07-22 17:00', 30, 70), (3, '2026-10-14 17:00', 30, 70);

INSERT INTO invoices (id, student_id, start_date, end_date, total, created_at, status, paid_at, paid_amount, paid_ref) VALUES
  (10, 1, '2026-04-20', '2026-07-04', 385, '2026-07-05 21:00:00', 'paid', '2026-07-12 10:00', 385, 'AROHA'),
  (11, 3, '2026-05-04', '2026-12-18', 900, '2026-05-05 21:00:00', 'paid', '2026-05-10 09:00', NULL, NULL),
  (12, 2, '2026-04-20', '2026-07-04', 320, '2026-07-05 21:00:00', 'void', NULL, NULL, NULL),
  (13, 2, '2026-01-26', '2026-04-03', 300, '2026-04-03 01:00:00', 'sent', '2026-04-20 09:00', 150, 'BEN PART'),
  (14, 1, '2026-01-26', '2026-04-03', 300, '2026-04-03 01:00:00', 'paid', '2026-04-20 09:00', 0, 'Replaced');
"""


@pytest.fixture
def upgraded(app, tmp_path):
    path = str(tmp_path / "live.db")
    make_live_shaped_db(path, ROWS)
    app.config["DB_PATH"] = path
    with app.app_context():
        db.init_db()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def test_the_first_register_terms_are_added_once(app, upgraded):
    with app.app_context():
        db.init_db()
    assert [tuple(r) for r in upgraded.execute("SELECT name, start_date, end_date FROM terms ORDER BY start_date")] == [
        ("Term 3 2026", "2026-07-20", "2026-09-25"), ("Term 4 2026", "2026-10-12", "2026-12-18")]


def test_each_students_regular_lesson_comes_from_their_recent_lessons(upgraded):
    rows = {r["id"]: tuple(r)[1:] for r in upgraded.execute(
        "SELECT id, lesson_day, lesson_start, lesson_minutes, lesson_rate FROM students ORDER BY id")}
    assert rows[1] == (1, "15:30", 30, 70.0)   # Mondays 3:30, not the one-off 4:00 lesson
    assert rows[2] == (2, "16:00", 45, 65.0)
    assert rows[4] == (None, None, None, None)


def test_lessons_are_linked_to_the_invoices_that_billed_them(upgraded):
    billed = {r[0]: r[1] for r in upgraded.execute("SELECT lesson_time || ' #' || student_id, invoice_id FROM lessons")}
    assert billed["2026-06-29 15:30 #1"] == 10      # in the Term 2 invoice's period
    assert billed["2026-07-10 15:30 #1"] == 0       # holiday lesson before Term 3, on no invoice: dealt with
    assert billed["2026-06-30 16:00 #2"] == 0       # his Term 2 invoice was void, so it didn't bill it
    assert billed["2026-07-20 15:30 #1"] is None    # Term 3: still to be billed
    assert billed["2026-07-21 16:00 #2"] is None
    assert billed["2026-07-22 17:00 #3"] == 11      # inside the May to December invoice
    assert billed["2026-10-14 17:00 #3"] == 11


def test_payments_move_to_their_own_table(upgraded):
    rows = [tuple(r) for r in upgraded.execute("SELECT invoice_id, paid_on, amount_cents, reference FROM payments ORDER BY invoice_id")]
    assert rows == [
        (10, "2026-07-12", 38500, "AROHA"),
        (11, "2026-05-10", 90000, None),   # marked paid without an amount: paid in full
        (13, "2026-04-20", 15000, "BEN PART"),
    ]                                       # the $0 and the void ones have no payment


def test_new_columns_default_sensibly(upgraded):
    lesson = upgraded.execute("SELECT status, kind, note FROM lessons LIMIT 1").fetchone()
    assert tuple(lesson) == ("taught", "regular", None)
    assert upgraded.execute("SELECT revision FROM invoices WHERE id=10").fetchone()[0] == 1
