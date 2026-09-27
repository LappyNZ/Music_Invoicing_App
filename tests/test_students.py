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

    assert "Ben Brown" not in page(client, "/invoices")               # Create
    add_lesson, lesson_filter = page(client, "/lessons").split('<form method="get"', 1)
    assert "Ben Brown" not in add_lesson
    assert "Ben Brown (archived)" in lesson_filter
    assert "Ben Brown (archived)" in page(client, "/invoices/list")   # filter
    assert "Ben Brown" in page(client, "/invoices/list")              # and his invoice is still listed
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

    listing = page(client, "/invoices/list")

    assert f"Deleted student #{ben}" in listing
    assert f"-{invoice:04d}" in listing


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
    listing = client.get("/invoices/list").get_data(as_text=True)
    assert "Deleted student #2" not in listing and "Ben Brown" in listing


def test_restoring_needs_the_upgraded_database(tmp_path, capsys):
    live, old = str(tmp_path / "live.db"), str(tmp_path / "old.db")
    make_live_shaped_db(live, LIVE)
    make_live_shaped_db(old, OLD_COPY)

    assert restore_deleted_students.main([old, "--db", live, "--apply"]) == 1
    assert "hasn't been upgraded" in capsys.readouterr().out
