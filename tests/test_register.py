"""The register (week by week and whole term), starting a term, and Home."""
import pytest

from helpers import page, weekly

FETCH = {"X-Requested-With": "fetch"}


@pytest.fixture(autouse=True)
def after_term3(today):
    today("2026-09-28")      # Term 3 2026 has just finished; Term 4 starts on 12 October


def status_of(db, lesson_id):
    return db.execute("SELECT status FROM lessons WHERE id=?", (lesson_id,)).fetchone()[0]


# ---------------------------------------------------------------- week by week

def test_a_week_shows_each_days_lessons_in_time_order(client, term3, student, lesson):
    alice, ben = student("Alice Aroha"), student("Ben Brown")
    lesson(ben, "2026-07-23 15:30", minutes=45)
    lesson(alice, "2026-07-21 16:00", note="bring the Bach")
    lesson(alice, "2026-07-28 16:00")                                    # week 2

    html = page(client, f"/register?term={term3['id']}&week=1")

    assert html.index("Tuesday 21 July") < html.index("Alice Aroha") < html.index("Thursday 23 July") < html.index("Ben Brown")
    assert "4:00 pm" in html and "3:30 pm" in html and "45 min" in html and "bring the Bach" in html
    assert "Tuesday 28 July" not in html
    assert "Week 1 is done" in html


def test_the_week_that_opens_first_is_the_first_one_not_checked(client, db, term3, student, lesson):
    alice = student()
    weekly(lesson, alice, weeks=3)
    db.execute("INSERT INTO register_checks (term_id, week, checked_at) VALUES (?, 1, 'x')", (term3["id"],))
    db.commit()

    assert "Week 2, Mon 27 Jul to Sun 2 Aug" in page(client, f"/register?term={term3['id']}")


def test_marking_a_lesson_changes_it_in_place(client, db, term3, student, lesson):
    lesson_id = lesson(student(), "2026-07-21 16:00")

    response = client.post(f"/register/lesson/{lesson_id}/status", data={"status": "cancelled"}, headers=FETCH)

    assert response.get_json() == {"ok": True, "status": "cancelled"}
    assert status_of(db, lesson_id) == "cancelled"


def test_without_javascript_marking_a_lesson_returns_to_it(client, db, term3, student, lesson):
    lesson_id = lesson(student(), "2026-07-21 16:00")

    response = client.post(f"/register/lesson/{lesson_id}/status",
                           data={"status": "missed", "term": term3["id"], "week": 1, "view": "week"})

    assert response.headers["Location"].endswith(f"/register?term={term3['id']}&week=1#lesson-{lesson_id}")
    assert status_of(db, lesson_id) == "missed"


def test_an_unknown_status_changes_nothing(client, db, student, lesson):
    lesson_id = lesson(student())

    response = client.post(f"/register/lesson/{lesson_id}/status", data={"status": "paid"}, headers=FETCH)

    assert response.status_code == 404 and status_of(db, lesson_id) == "taught"


def test_a_holiday_lesson_can_be_marked_as_happened(client, db, term3, student, lesson):
    lesson_id = lesson(student(), "2026-07-21 16:00", status="holiday")
    assert "Holiday: no lesson" in page(client, f"/register?term={term3['id']}&week=1")

    client.post(f"/register/lesson/{lesson_id}/status", data={"status": "taught", "term": term3["id"], "week": 1})

    assert status_of(db, lesson_id) == "taught"


def test_changing_a_lesson(client, db, term3, student, lesson):
    lesson_id = lesson(student(), "2026-07-21 16:00")

    client.post(f"/register/lesson/{lesson_id}/edit", data={"date": "2026-07-22", "time": "17:15", "minutes": "45",
                                                             "rate": "65", "note": "moved", "term": term3["id"], "week": 1})

    row = db.execute("SELECT lesson_time, duration, rate, note FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    assert tuple(row) == ("2026-07-22 17:15", 45, 65.0, "moved")


@pytest.mark.parametrize("field, value", [("date", "22/07/2026"), ("minutes", "half an hour"), ("rate", "nan"), ("minutes", "0")])
def test_a_change_that_cannot_be_read_changes_nothing(client, db, term3, student, lesson, field, value):
    lesson_id = lesson(student(), "2026-07-21 16:00")
    form = {"date": "2026-07-22", "time": "17:15", "minutes": "45", "rate": "65", "term": term3["id"], "week": 1, field: value}

    html = client.post(f"/register/lesson/{lesson_id}/edit", data=form, follow_redirects=True).get_data(as_text=True)

    assert "Nothing was changed" in html
    assert db.execute("SELECT lesson_time, duration FROM lessons WHERE id=?", (lesson_id,)).fetchone()[0] == "2026-07-21 16:00"


def test_changing_a_lesson_on_a_sent_invoice_says_so(client, db, term3, student, lesson):
    lesson_id = lesson(student(), "2026-07-21 16:00")
    client.post("/invoices/make", data={"term": term3["id"]})
    invoice = db.execute("SELECT id, invoice_number FROM invoices").fetchone()
    client.post(f"/invoices/{invoice['id']}/mark-sent")

    html = client.post(f"/register/lesson/{lesson_id}/edit", follow_redirects=True,
                       data={"date": "2026-07-21", "time": "16:00", "minutes": "60", "rate": "70", "term": term3["id"], "week": 1}
                       ).get_data(as_text=True)

    assert f"It’s on {invoice['invoice_number']}, which has been sent" in html


def test_deleting_a_lesson(client, db, term3, student, lesson):
    lesson_id = lesson(student())

    client.post(f"/register/lesson/{lesson_id}/delete", data={"term": term3["id"], "week": 1})

    assert db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 0


def test_an_extra_lesson_uses_the_students_own_rate(client, db, term3, student, lesson):
    alice = student(lesson_rate=55)
    ben = student("Ben Brown")
    lesson(ben, "2026-07-20 15:30", rate=65)
    carl = student("Carl Chen")

    for who in (alice, ben, carl):
        client.post("/register/extra", data={"student_id": who, "date": "2026-07-24", "time": "10:00", "minutes": "30",
                                             "note": "makeup", "term": term3["id"], "week": 1})

    extras = db.execute("SELECT student_id, rate, kind, status, note FROM lessons WHERE kind='extra' ORDER BY student_id").fetchall()
    assert [tuple(r) for r in extras] == [(alice, 55.0, "extra", "taught", "makeup"), (ben, 65.0, "extra", "taught", "makeup"),
                                          (carl, 70.0, "extra", "taught", "makeup")]


def test_a_student_starting_partway_gets_the_rest_of_the_term(client, db, term3, student):
    alice = student()
    db.execute("INSERT INTO term_holidays (term_id, date, name) VALUES (?, '2026-08-11', 'Teacher away')", (term3["id"],))
    db.commit()

    client.post("/register/weekly", data={"student_id": alice, "from_week": "3", "day": "2", "time": "16:00", "minutes": "30",
                                          "rate": "70", "term": term3["id"], "week": 3})

    lessons = db.execute("SELECT date(lesson_time), status FROM lessons ORDER BY lesson_time").fetchall()
    assert len(lessons) == 8 and lessons[0][0] == "2026-08-04" and lessons[-1][0] == "2026-09-22"
    assert ("2026-08-11", "holiday") in [tuple(r) for r in lessons]
    regular = db.execute("SELECT lesson_day, lesson_start, lesson_minutes, lesson_rate FROM students").fetchone()
    assert tuple(regular) == (2, "16:00", 30, 70.0)


def test_cancelling_a_whole_day(client, db, term3, student, lesson):
    first, second = lesson(student(), "2026-07-21 15:00"), lesson(student("Ben Brown"), "2026-07-21 16:00")
    other_day = lesson(student("Carl Chen"), "2026-07-22 16:00")

    client.post("/register/day/cancel", data={"date": "2026-07-21", "term": term3["id"], "week": 1})

    assert [status_of(db, i) for i in (first, second, other_day)] == ["cancelled", "cancelled", "taught"]


def test_checking_a_week_moves_on_to_the_next_unchecked_one(client, db, term3):
    response = client.post("/register/week", data={"term": term3["id"], "week": 1, "checked": "1"})

    assert response.headers["Location"].endswith(f"/register?term={term3['id']}&week=2")
    client.post("/register/week", data={"term": term3["id"], "week": 1, "checked": "0"})
    assert db.execute("SELECT COUNT(*) FROM register_checks").fetchone()[0] == 0


# ---------------------------------------------------------------- whole term

def test_the_whole_term_shows_each_student_and_what_they_are_charged(client, db, term3, student, lesson):
    alice = student()
    lessons = weekly(lesson, alice, weeks=10, minutes=30, rate=70)
    db.execute("UPDATE lessons SET status='cancelled' WHERE id=?", (lessons[2],))
    db.execute("UPDATE lessons SET status='missed' WHERE id=?", (lessons[3],))
    db.commit()
    lesson(alice, "2026-10-01 10:00", kind="extra")                     # a makeup in the holidays

    html = page(client, f"/register?term={term3['id']}&view=term")

    assert "Hol" in html                                                  # the holiday week is shown
    assert "<td class=\"money\">10</td>" in html and "$350.00" in html   # 9 charged + the makeup, at $35 each


def test_a_click_in_the_whole_term_moves_a_lesson_to_the_next_status(client, db, term3, student, lesson):
    lesson_id = lesson(student(), "2026-07-21 16:00")

    answers = [client.post(f"/register/lesson/{lesson_id}/cycle", headers=FETCH).get_json()["symbol"] for _ in range(3)]

    assert answers == ["✗", "$", "✓"]
    assert status_of(db, lesson_id) == "taught"


# ---------------------------------------------------------------- starting a term

def start_form(term, students, action="start", **extra):
    form = {"term": term["id"], "name": term["name"], "start": term["start_date"], "end": term["end_date"], "action": action,
            "hol_2026-10-26": "1", "holname_2026-10-26": "Labour Day"}
    for sid, (day, time, minutes, rate) in students.items():
        form.update({f"include_{sid}": "1", f"day_{sid}": day, f"time_{sid}": time, f"minutes_{sid}": minutes, f"rate_{sid}": rate})
    form.update(extra)
    return form


def test_the_start_page_suggests_the_known_days_off_and_everyones_regular_lesson(client, term4, student):
    student("Alice Aroha", lesson_day=1, lesson_start="15:30", lesson_minutes=30, lesson_rate=70)
    student("Ben Brown")                                                   # no regular lesson known yet

    html = page(client, "/terms/start")

    assert "Start Term 4 2026" in html
    assert 'name="hol_2026-10-26" value="1" id="hol-2026-10-26" checked' in html
    assert 'name="hol_2026-11-13" value="1" id="hol-2026-11-13" checked' in html
    assert "Monday 26 October: Labour Day" in html
    assert 'value="15:30"' in html and "Choose a day, time, length and rate." in html
    assert "Add <b>9 lessons</b> for 1 student" in html                    # 10 Mondays, less Labour Day


def test_starting_a_term_adds_weekly_lessons_and_marks_days_off(client, db, term4, student):
    alice, ben = student("Alice Aroha"), student("Ben Brown")

    response = client.post("/terms/start", data=start_form(term4, {alice: ("1", "15:30", "30", "70"),
                                                                   ben: ("5", "16:00", "45", "60")}))

    assert response.headers["Location"].endswith(f"/register?term={term4['id']}&week=1")
    rows = db.execute("SELECT student_id, lesson_time, duration, rate, status FROM lessons ORDER BY lesson_time").fetchall()
    assert len([r for r in rows if r["student_id"] == alice]) == 10 and len([r for r in rows if r["student_id"] == ben]) == 10
    assert [r["lesson_time"] for r in rows if r["status"] == "holiday"] == ["2026-10-26 15:30"]
    assert rows[0]["lesson_time"] == "2026-10-12 15:30" and rows[-1]["lesson_time"] == "2026-12-18 16:00"
    assert {(r["duration"], r["rate"]) for r in rows if r["student_id"] == ben} == {(45, 60.0)}
    assert db.execute("SELECT started_at IS NOT NULL FROM terms WHERE id=?", (term4["id"],)).fetchone()[0] == 1
    assert [tuple(r) for r in db.execute("SELECT date, name FROM term_holidays")] == [("2026-10-26", "Labour Day")]
    assert tuple(db.execute("SELECT lesson_day, lesson_start, lesson_minutes, lesson_rate FROM students WHERE id=?", (ben,)).fetchone()) == (5, "16:00", 45, 60.0)


def test_starting_keeps_lessons_already_entered_but_gives_them_the_new_rate(client, db, term4, student, lesson):
    alice = student("Alice Aroha", lesson_day=1, lesson_start="15:30", lesson_minutes=30, lesson_rate=70)
    entered = weekly(lesson, alice, weeks=11, start="2026-10-12", time="15:30", rate=70)   # one week too many, to 21 Dec

    preview = client.post("/terms/start", data=start_form(term4, {alice: ("1", "15:30", "30", "60")}, action="preview")).get_data(as_text=True)
    assert "Keep the lessons already entered for 1 student" in preview
    assert "Also delete the <b>1 lesson</b> entered after the last day" in preview
    assert db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 11                 # a check changes nothing

    client.post("/terms/start", data=start_form(term4, {alice: ("1", "15:30", "30", "60")}, drop_after="1"))

    rows = db.execute("SELECT id, rate, status FROM lessons ORDER BY lesson_time").fetchall()
    assert [r["id"] for r in rows] == entered[:10]
    assert {r["rate"] for r in rows} == {60.0}
    assert [r["status"] for r in rows].count("holiday") == 1


def test_a_day_off_unticked_later_puts_its_lessons_back(client, db, term4, student):
    alice = student()
    client.post("/terms/start", data=start_form(term4, {alice: ("1", "15:30", "30", "70")}))
    assert db.execute("SELECT COUNT(*) FROM lessons WHERE status='holiday'").fetchone()[0] == 1

    form = start_form(term4, {alice: ("1", "15:30", "30", "70")})
    del form["hol_2026-10-26"]
    client.post("/terms/start", data=form)

    assert db.execute("SELECT COUNT(*) FROM lessons WHERE status='holiday'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 10


def test_a_day_off_added_on_the_page_is_kept(client, db, term4, student):
    alice = student()
    form = start_form(term4, {alice: ("3", "15:30", "30", "70")}, action="preview", extra_date_0="2026-11-04", extra_name_0="Away")

    html = client.post("/terms/start", data=form).get_data(as_text=True)

    assert 'name="hol_2026-11-04" value="1" id="hol-2026-11-04" checked' in html
    assert 'name="holname_2026-11-04" value="Away"' in html


def test_the_next_term_can_be_added(client, db, term4, student, today):
    db.execute("UPDATE terms SET started_at='2026-10-01 09:00'")
    db.commit()
    alice = student()

    html = page(client, "/terms/start")
    assert "Start Term 1 2027" in html and 'value="2027-02-01"' in html

    client.post("/terms/start", data={"name": "Term 1 2027", "start": "2027-02-02", "end": "2027-04-16", "action": "start",
                                      f"include_{alice}": "1", f"day_{alice}": "2", f"time_{alice}": "15:30",
                                      f"minutes_{alice}": "30", f"rate_{alice}": "70"})

    term = db.execute("SELECT * FROM terms WHERE name='Term 1 2027'").fetchone()
    assert (term["start_date"], term["end_date"]) == ("2027-02-02", "2027-04-16")
    assert db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 11


@pytest.mark.parametrize("start, end, message", [("2026-12-18", "2026-10-12", "needs to be after"),
                                                  ("soon", "2026-12-18", "need to be dates"),
                                                  ("2026-07-20", "2026-09-25", "already starts that day")])
def test_term_dates_that_do_not_work_change_nothing(client, db, term4, student, start, end, message):
    alice = student()

    html = client.post("/terms/start", data=start_form(term4, {alice: ("1", "15:30", "30", "70")}, start=start, end=end)).get_data(as_text=True)

    assert message in html
    assert db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] == 0


# ---------------------------------------------------------------- Home

def test_home_leads_through_the_end_of_term(client, db, term3, student, lesson, gmail):
    alice = student()
    weekly(lesson, alice, weeks=10)

    assert "Check weeks 1 to 10 in the register" in page(client, "/")
    for week in range(1, 11):
        client.post("/register/week", data={"term": term3["id"], "week": week, "checked": "1"})
    assert "Make the Term 3 2026 invoices" in page(client, "/")

    client.post("/invoices/make", data={"term": term3["id"]})
    assert "Check and send 1 invoice" in page(client, "/")

    invoice = db.execute("SELECT id FROM invoices").fetchone()[0]
    client.post(f"/invoices/{invoice}/send")
    html = page(client, "/")
    assert "Get Term 4 2026 ready" in html
    assert "Waiting for payment" in html and "$350.00" in html


def test_home_moves_on_to_sending_once_invoices_are_made(client, db, term3, student, lesson):
    weekly(lesson, student(), weeks=10)

    client.post("/invoices/make", data={"term": term3["id"]})

    html = page(client, "/")
    assert "Check and send 1 invoice" in html
    assert "Weeks 1 to 10 aren’t checked in the register yet" in html


def test_home_before_any_term(client, db):
    db.execute("DELETE FROM terms")
    db.commit()

    assert "Set up your first term" in page(client, "/")
