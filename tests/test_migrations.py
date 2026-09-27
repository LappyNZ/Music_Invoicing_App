import sqlite3

import pytest

import db
from live_schema import make_live_shaped_db

# Shaped like the production data in September 2026 (made-up people and amounts).
ROWS = """
INSERT INTO students (id, name, email) VALUES (1, 'Alice', 'a@example.com'), (2, 'Ben', 'b@example.com');

-- Lesson times: the normal form, one saved with a 'T', one pasted in display form that duplicates an
-- existing lesson, one pasted in display form with no duplicate, and one nobody could read.
INSERT INTO lessons (id, student_id, lesson_time, duration, rate) VALUES
  (1, 1, '2026-04-21 18:00', 30, 60),
  (2, 1, 'Wed, 21 Apr 26, 6:00PM', 30, 60),
  (3, 2, 'Tue, 28 Apr 26, 4:15PM', 45, 60),
  (4, 2, '2026-05-05T16:15', 45, 60),
  (5, 2, 'sometime in May', 45, 60);

-- Invoices: created_at is UTC (SQLite's clock).
INSERT INTO invoices (id, student_id, start_date, end_date, total, created_at, status, emailed_at, paid_at, paid_amount, paid_ref) VALUES
  (6,  1, '2025-07-14', '2025-09-23', 300, '2025-09-08 19:51:00', 'paid', '2025-09-09 08:00:00', '2025-09-12T10:30', 300, 'ALICE'),
  (95, 1, '2026-04-20', '2026-07-04', 540, '2026-07-07 09:01:00', 'paid', NULL, '2026-07-18T09:00', 0, 'Wrong inv'),
  (96, 1, '2026-04-20', '2026-07-04', 510, '2026-07-07 21:04:00', 'sent', '2026-07-18 09:05:00', NULL, NULL, NULL),
  (97, 2, '2026-04-20', '2026-07-04', 450, '2026-07-07 21:10:00', 'paid', '2026-07-18 09:10:00', '2026-07-20 01:30:00', 0, NULL),
  (98, 2, '2026-01-26', '2026-04-03', 450, '2026-04-03 01:00:00', 'paid', '2026-04-03 13:05:00', '2026-04-10 09:15', 450, 'BEN T1');
"""


@pytest.fixture
def upgraded(app, tmp_path, new_zealand_time):
    """The live-shaped database after the app has started on it."""
    path = str(tmp_path / "live.db")
    make_live_shaped_db(path, ROWS)
    app.config["DB_PATH"] = path
    with app.app_context():
        db.init_db()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def invoice(conn, invoice_id):
    return conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()


def test_every_fix_is_recorded(upgraded):
    assert upgraded.execute("PRAGMA user_version").fetchone()[0] == len(db.DATA_FIXES)


def test_existing_invoices_keep_the_numbers_and_files_they_already_had(upgraded):
    rows = upgraded.execute("SELECT id, invoice_number, pdf_filename FROM invoices ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        (6, "INV-2025-0006", "INV-2025-0006.pdf"),
        (95, "INV-2026-0095", "INV-2026-0095.pdf"),
        (96, "INV-2026-0096", "INV-2026-0096.pdf"),
        (97, "INV-2026-0097", "INV-2026-0097.pdf"),
        (98, "INV-2026-0098", "INV-2026-0098.pdf"),
    ]


def test_paid_at_is_stored_the_same_way_in_new_zealand_time(upgraded):
    assert invoice(upgraded, 6)["paid_at"] == "2025-09-12 10:30"    # the form's 'T' removed
    assert invoice(upgraded, 98)["paid_at"] == "2026-04-10 09:15"   # already fine
    assert invoice(upgraded, 97)["paid_at"] == "2026-07-20 13:30"   # was UTC (left blank): now NZST


def test_unreadable_lesson_times_are_repaired_or_removed_if_duplicates(upgraded):
    times = dict(upgraded.execute("SELECT id, lesson_time FROM lessons").fetchall())
    assert times == {
        1: "2026-04-21 18:00",
        # 2 was the same lesson as 1, pasted in display form: removed
        3: "2026-04-28 16:15",
        4: "2026-05-05 16:15",
        5: "sometime in May",   # can't be read, so it's left for a person (the Lessons page flags it)
    }


def test_zero_payments_on_replaced_invoices_become_void(upgraded):
    replaced = invoice(upgraded, 95)
    assert (replaced["status"], replaced["void_reason"], replaced["voided_at"]) == ("void", "Wrong inv", "2026-07-18 09:00")
    # A $0 payment with no later invoice for the same period might be a waived fee: left alone.
    assert invoice(upgraded, 97)["status"] == "paid"
    assert invoice(upgraded, 96)["status"] == "sent"
    assert invoice(upgraded, 6)["status"] == "paid"


def test_starting_again_changes_nothing(app, upgraded):
    before = [tuple(r) for r in upgraded.execute("SELECT * FROM invoices ORDER BY id")]
    lessons_before = [tuple(r) for r in upgraded.execute("SELECT * FROM lessons ORDER BY id")]
    with app.app_context():
        db.init_db()
    assert [tuple(r) for r in upgraded.execute("SELECT * FROM invoices ORDER BY id")] == before
    assert [tuple(r) for r in upgraded.execute("SELECT * FROM lessons ORDER BY id")] == lessons_before


def test_a_failing_fix_leaves_the_database_as_it_was(app, tmp_path, monkeypatch):
    path = str(tmp_path / "live.db")
    make_live_shaped_db(path, ROWS)

    def broken(cur):
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "DATA_FIXES", db.DATA_FIXES[:2] + [broken])
    app.config["DB_PATH"] = path
    with app.app_context(), pytest.raises(RuntimeError):
        db.init_db()

    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "invoice_number" not in [r[1] for r in conn.execute("PRAGMA table_info(invoices)")]
    assert conn.execute("SELECT paid_at FROM invoices WHERE id=6").fetchone()[0] == "2025-09-12T10:30"
    conn.close()
