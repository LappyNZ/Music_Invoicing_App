import os
import sqlite3
import subprocess
import sys

from db import DATA_FIXES


def test_adding_a_lesson_with_weeks_repeating_left_blank_adds_one_lesson(client, db, make_student):
    alice = make_student()

    resp = client.post("/lessons", data={
        "student_id": alice, "lesson_time": "2026-10-12T15:00", "duration": "30", "rate": "60", "repeat_weeks": "",
    })

    assert resp.status_code == 302
    assert [tuple(r) for r in db.execute("SELECT lesson_time, duration FROM lessons")] == [("2026-10-12 15:00", 30)]


def test_weeks_repeating_adds_one_lesson_per_week(client, db, make_student):
    alice = make_student()

    client.post("/lessons", data={
        "student_id": alice, "lesson_time": "2026-10-12T15:00", "duration": "30", "rate": "60", "repeat_weeks": "3",
    })

    assert [r[0] for r in db.execute("SELECT lesson_time FROM lessons ORDER BY lesson_time")] == [
        "2026-10-12 15:00", "2026-10-19 15:00", "2026-10-26 15:00"]


def test_version_endpoint_and_footer_show_the_build(client):
    assert client.get("/version").get_json() == {"version": "0123456789abcdef"}
    assert "Version 0123456" in client.get("/").get_data(as_text=True)


def test_the_dev_database_script_builds_a_database_the_app_can_use(tmp_path):
    script = os.path.join(os.path.dirname(__file__), os.pardir, "scripts", "reset_dev_db.py")
    subprocess.run([sys.executable, script, str(tmp_path)], check=True, capture_output=True)

    conn = sqlite3.connect(tmp_path / "music_school_dev.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(DATA_FIXES)
    assert conn.execute("SELECT status FROM invoices ORDER BY id").fetchall() == [
        ("paid",), ("draft",), ("draft",), ("draft",), ("draft",), ("sent",)]
    assert conn.execute("SELECT COUNT(DISTINCT student_id) FROM lessons WHERE invoice_id = 3").fetchone()[0] == 2   # the Wu family
    assert conn.execute("SELECT COUNT(*) FROM register_checks").fetchone()[0] == 10
    assert conn.execute("SELECT status, COUNT(*) FROM lessons GROUP BY status ORDER BY status").fetchall() == [
        ("cancelled", 1), ("holiday", 1), ("missed", 1), ("taught", 64)]
    assert conn.execute("SELECT COUNT(*) FROM students WHERE active = 0").fetchone()[0] == 1
    conn.close()
    assert len(os.listdir(tmp_path / "invoices_pdfs")) == 2
