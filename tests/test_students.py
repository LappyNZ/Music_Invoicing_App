import sqlite3

import pytest

from live_schema import make_live_shaped_db
from tools import restore_deleted_students


def page(client, url):
    return client.get(url).get_data(as_text=True)


def test_an_archived_student_is_not_offered_for_new_lessons_or_invoices(client, make_student, make_invoice):
    make_student("Alice Aroha")
    ben = make_student("Ben Brown")
    make_invoice(ben)

    client.post(f"/students/archive/{ben}", follow_redirects=True)

    assert "Ben Brown" not in page(client, "/invoices")               # the one-off invoice form
    assert "Ben Brown" not in page(client, "/register")               # extra lessons, starting partway through
    assert "Ben Brown" not in page(client, "/terms/start")            # weekly lessons for a new term
    add_lesson, lesson_filter = page(client, "/lessons").split('<form method="get"', 1)
    assert "Ben Brown" not in add_lesson
    assert "Ben Brown (archived)" in lesson_filter
    assert "Ben Brown" in page(client, "/invoices?show=all")          # and his invoice is still listed
    assert "Alice Aroha" in page(client, "/invoices")


def test_archived_students_are_listed_separately_and_can_be_restored(client, db, make_student):
    ben = make_student("Ben Brown")

    page_after = client.post(f"/students/archive/{ben}", follow_redirects=True).get_data(as_text=True)
    assert "Ben Brown archived" in page_after
    assert "Ben Brown" not in page(client, "/students").split("<table")[1]
    assert "Ben Brown" in page(client, "/students?show=archived").split("<table")[1]
    assert db.execute("SELECT archived_at FROM students WHERE id=?", (ben,)).fetchone()[0]

    client.post(f"/students/restore/{ben}", data={"return_show": "archived"})
    assert tuple(db.execute("SELECT active, archived_at FROM students WHERE id=?", (ben,)).fetchone()) == (1, None)
    assert "Ben Brown" in page(client, "/students").split("<table")[1]


def test_a_student_with_invoices_cannot_be_deleted(client, db, make_student, make_lesson, make_invoice):
    ben = make_student("Ben Brown")
    make_lesson(ben)
    make_invoice(ben)

    assert f"/students/delete/{ben}" not in page(client, "/students")
    response = client.post(f"/students/delete/{ben}", follow_redirects=True)

    assert "can&#39;t be deleted" in response.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 1


def test_a_student_on_a_family_invoice_cannot_be_deleted(client, db, today, term3, student, lesson):
    today("2026-09-28")
    alice, ben = student("Alice Aroha", "pat@example.com"), student("Ben Aroha", "pat@example.com")
    lesson(alice)
    lesson(ben, "2026-07-20 16:00")
    client.post("/invoices/make", data={"term": term3["id"], "family": "1"})

    assert f"/students/delete/{ben}" not in page(client, "/students")
    client.post(f"/students/delete/{ben}")

    assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 2


def test_a_student_added_by_mistake_can_be_deleted_with_their_lessons(client, db, make_student, make_lesson):
    ben = make_student("Ben Brown")
    make_lesson(ben)
    make_lesson(ben, "2026-07-27 15:00")

    assert "Their 2 lessons will also be deleted" in page(client, "/students")
    client.post(f"/students/delete/{ben}")

    assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 0


def test_student_actions_keep_the_list_filters(client, make_student):
    ben = make_student("Ben Brown")

    response = client.post(f"/students/archive/{ben}",
                           data={"return_show": "all", "return_school": "__blank__", "return_q": "ben"})

    assert response.headers["Location"].endswith("/students?show=all&school=__blank__&q=ben")


def test_students_with_no_school_can_be_filtered(client, db, make_student):
    alice = make_student("Alice Aroha")
    make_student("Ben Brown")
    db.execute("UPDATE students SET school='Burnside High' WHERE id=?", (alice,))
    db.commit()

    table = page(client, "/students?school=__blank__").split("<table")[1]

    assert "Ben Brown" in table and "Alice Aroha" not in table
    assert 'value="__blank__" selected' in page(client, "/students?school=__blank__")


def test_invoices_of_a_deleted_student_still_show(client, db, make_student, make_invoice):
    ben = make_student("Ben Brown")
    invoice = make_invoice(ben)
    db.execute("PRAGMA foreign_keys = OFF")  # how it was left by the old Delete
    db.execute("DELETE FROM students WHERE id=?", (ben,))
    db.commit()

    listing = page(client, "/invoices?show=all")

    assert f"Deleted student #{ben}" in listing
    assert f"-{invoice:04d}" in listing
    assert f"Deleted student #{ben}" in page(client, f"/invoices/{invoice}")


# ---------------- Regular lessons ----------------

def regular(db, student_id):
    return tuple(db.execute("SELECT lesson_day, lesson_start, lesson_minutes, lesson_rate FROM students WHERE id=?",
                            (student_id,)).fetchone())


def test_a_student_can_be_added_with_their_regular_lesson(client, db):
    client.post("/students", data={"name": "Alice Aroha", "email": "pat@example.com", "parent": "Pat Aroha", "phone": "",
                                   "lesson_day": "2", "lesson_start": "16:00", "lesson_minutes": "45", "lesson_rate": "65"})

    assert regular(db, 1) == (2, "16:00", 45, 65.0)
    assert "Tue 4:00 pm, 45 min, $65/h" in page(client, "/students")


def test_parts_of_a_regular_lesson_that_cannot_be_read_are_left_blank(client, db):
    client.post("/students", data={"name": "Alice Aroha", "email": "pat@example.com", "phone": "",
                                   "lesson_day": "9", "lesson_start": "4pm", "lesson_minutes": "30", "lesson_rate": "nan"})

    assert regular(db, 1) == (None, None, 30, None)


def edit(client, student_id, rate, apply_rate="1"):
    return client.post(f"/students/edit/{student_id}", follow_redirects=True, data={
        "name": "Alice Aroha", "email": "pat@example.com", "parent": "Pat Aroha", "phone": "", "school": "",
        "lesson_day": "1", "lesson_start": "15:30", "lesson_minutes": "30", "lesson_rate": rate, "apply_rate": apply_rate,
    }).get_data(as_text=True)


def test_a_lower_rate_is_used_for_lessons_not_invoiced_yet(client, db, today, term3, student, lesson, gmail):
    today("2026-09-28")
    alice = student("Alice Aroha", lesson_rate=70)
    billed = lesson(alice, "2026-07-20 15:30")
    client.post("/invoices/make", data={"term": term3["id"]})
    draft = db.execute("SELECT id FROM invoices").fetchone()[0]
    client.post(f"/invoices/{draft}/send")                                   # this one has gone at $70
    later = [lesson(alice, "2026-10-12 15:30"), lesson(alice, "2026-10-19 15:30"), lesson(alice, "2026-10-21 10:00", kind="extra")]

    html = edit(client, alice, "60")

    assert "2 lessons not invoiced yet now use $60 an hour" in html
    rates = dict(db.execute("SELECT id, rate FROM lessons").fetchall())
    assert (rates[billed], rates[later[0]], rates[later[1]], rates[later[2]]) == (70.0, 60.0, 60.0, 70.0)


def test_the_rate_can_change_for_next_term_only(client, db, student, lesson):
    alice = student("Alice Aroha", lesson_rate=70)
    entered = lesson(alice, "2026-10-12 15:30")

    edit(client, alice, "60", apply_rate="")

    assert regular(db, alice)[3] == 60.0
    assert db.execute("SELECT rate FROM lessons WHERE id=?", (entered,)).fetchone()[0] == 70.0


# ---------------- Bringing back deleted students from an old copy ----------------

LIVE = """
INSERT INTO students (id, name, email) VALUES (1, 'Alice', 'a@example.com');
INSERT INTO invoices (id, student_id, start_date, end_date, total, created_at, status) VALUES
  (10, 1, '2025-07-14', '2025-09-23', 300, '2025-09-08 19:51:00', 'paid'),
  (11, 2, '2025-04-28', '2025-07-04', 280, '2025-06-30 02:00:00', 'paid'),
  (12, 2, '2025-07-14', '2025-09-23', 300, '2025-09-08 19:55:00', 'paid'),
  (13, 3, '2025-07-14', '2025-09-23', 150, '2025-09-08 19:58:00', 'paid'),
  (14, 4, '2025-10-13', '2025-12-19', 150, '2025-12-01 01:00:00', 'paid');
"""

OLD_COPY = """
INSERT INTO students (id, name, email, parent, phone, school) VALUES
  (1, 'Alice', 'a@example.com', NULL, NULL, NULL),
  (2, 'Ben Brown', 'ben@example.com', 'Bea Brown', '021 000', 'Burnside High'),
  (3, 'Cara', 'c@example.com', NULL, NULL, NULL);
INSERT INTO invoices (id, student_id, start_date, end_date, total, created_at) VALUES
  (10, 1, '2025-07-14', '2025-09-23', 300, '2025-09-08 19:51:00'),
  (11, 2, '2025-04-28', '2025-07-04', 280, '2025-06-30 02:00:00'),
  (13, 1, '2025-07-14', '2025-09-23', 150, '2025-09-08 19:58:00');
"""


@pytest.fixture
def copies(app, tmp_path):
    live, old = str(tmp_path / "live.db"), str(tmp_path / "old.db")
    make_live_shaped_db(live, LIVE)
    make_live_shaped_db(old, OLD_COPY)
    app.config["DB_PATH"] = live
    with app.app_context():
        from db import init_db
        init_db()
    return live, old


def students_in(path):
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT id, name, parent, school, active, archived_at IS NOT NULL FROM students ORDER BY id").fetchall()
    conn.close()
    return rows


def test_restoring_shows_what_would_happen_and_changes_nothing(copies, capsys):
    live, old = copies

    assert restore_deleted_students.main([old, "--db", live]) == 0

    out = capsys.readouterr().out
    assert "4 invoice(s) belong to 3 deleted student(s)" in out
    assert "Ben Brown (Bea Brown, ben@example.com)" in out
    assert "Nothing has been changed. Run again with --apply to bring back 1 student(s)." in out
    assert students_in(live) == [(1, "Alice", None, None, 1, 0)]


def test_restoring_brings_back_only_proven_students_as_archived(copies, client, capsys):
    live, old = copies

    restore_deleted_students.main([old, "--db", live, "--apply"])

    out = capsys.readouterr().out
    assert "Same person: INV-2025-0011 is in that copy too." in out
    assert "may be a different person" in out               # Cara: #13 belongs to someone else in the old copy
    assert "not in any of the old copies" in out            # student #4
    assert students_in(live) == [(1, "Alice", None, None, 1, 0), (2, "Ben Brown", "Bea Brown", "Burnside High", 0, 1)]
    listing = client.get("/invoices?show=all").get_data(as_text=True)
    assert "Deleted student #2" not in listing and "Ben Brown" in listing


def test_restoring_needs_the_upgraded_database(tmp_path, capsys):
    live, old = str(tmp_path / "live.db"), str(tmp_path / "old.db")
    make_live_shaped_db(live, LIVE)
    make_live_shaped_db(old, OLD_COPY)

    assert restore_deleted_students.main([old, "--db", live, "--apply"]) == 1
    assert "hasn't been upgraded" in capsys.readouterr().out
