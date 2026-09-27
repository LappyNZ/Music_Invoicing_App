from datetime import date, timedelta

import pytest


def lesson_times(db):
    return [r[0] for r in db.execute("SELECT lesson_time FROM lessons ORDER BY id")]


def days_from_today(days, time="15:00"):
    return f"{date.today() + timedelta(days=days)} {time}"


@pytest.fixture
def ben(make_student):
    return make_student("Ben Brown")


def test_an_edited_time_is_stored_the_standard_way(client, db, ben, make_lesson):
    lesson = make_lesson(ben, "2026-07-20 15:00")

    client.post(f"/lessons/edit/{lesson}",
                data={"student_id": ben, "lesson_time": "2026-07-21T16:30", "duration": "45", "rate": "60"})

    assert tuple(db.execute("SELECT lesson_time, duration, rate FROM lessons").fetchone()) == ("2026-07-21 16:30", 45, 60.0)


@pytest.mark.parametrize("field, value, message", [
    ("lesson_time", "next Tuesday", "lesson time wasn"),
    ("duration", "", "must be numbers"),
    ("rate", "sixty", "must be numbers"),
    ("rate", "nan", "must be numbers"),
])
def test_an_edit_that_cannot_be_read_changes_nothing(client, db, ben, make_lesson, field, value, message):
    lesson = make_lesson(ben, "2026-07-20 15:00")
    form = {"student_id": ben, "lesson_time": "2026-07-21T16:30", "duration": "45", "rate": "60", field: value}

    response = client.post(f"/lessons/edit/{lesson}", data=form, follow_redirects=True)

    assert message in response.get_data(as_text=True).replace("&#39;", "'")
    assert "Nothing was changed" in response.get_data(as_text=True)
    assert lesson_times(db) == ["2026-07-20 15:00"]


def test_a_lesson_that_cannot_be_read_is_not_added(client, db, ben):
    response = client.post("/lessons", data={"student_id": ben, "lesson_time": "soon", "duration": "30", "rate": "60"},
                           follow_redirects=True)

    assert "Nothing was added" in response.get_data(as_text=True)
    assert lesson_times(db) == []


def test_the_date_filter_includes_lessons_on_the_end_date(client, ben, make_lesson):
    make_lesson(ben, "2026-07-20 15:00")
    make_lesson(ben, "2026-07-27 15:00")

    page = client.get("/lessons?start_date=2026-07-20&end_date=2026-07-27").get_data(as_text=True)

    assert "Mon, 20 Jul 26" in page and "Mon, 27 Jul 26" in page


def test_first_visit_shows_recent_and_coming_lessons_only(client, ben, make_lesson):
    for days in (-60, 0, 60, 120):
        make_lesson(ben, days_from_today(days))

    first_visit = client.get("/lessons").get_data(as_text=True)
    everything = client.get("/lessons?start_date=&end_date=").get_data(as_text=True)

    assert first_visit.count('data-bs-target="#editLessonModal"') == 2
    assert "Show all dates" in first_visit
    assert everything.count('data-bs-target="#editLessonModal"') == 4


def test_one_edit_and_one_delete_dialog_however_many_lessons(client, ben, make_lesson):
    for week in range(20):
        make_lesson(ben, f"2026-{7 + week // 4:02d}-{1 + (week % 4) * 7:02d} 15:00")

    page = client.get("/lessons?start_date=&end_date=").get_data(as_text=True)

    assert page.count('class="modal fade"') == 2
    assert page.count('data-bs-target="#deleteLessonModal"') == 20


def test_unreadable_times_are_always_shown_and_flagged(client, ben, make_lesson):
    make_lesson(ben, "sometime in May")
    make_lesson(ben, days_from_today(-200))

    page = client.get("/lessons").get_data(as_text=True)

    assert "1 lesson below has a time" in page
    assert "Time not understood" in page
    assert 'data-raw-time="sometime in May"' in page
    assert page.count('data-bs-target="#editLessonModal"') == 1


def test_editing_keeps_the_filters_even_all_dates(client, ben, make_lesson):
    lesson = make_lesson(ben)

    response = client.post(f"/lessons/edit/{lesson}", data={
        "student_id": ben, "lesson_time": "2026-07-21T16:30", "duration": "45", "rate": "60",
        "return_student_id": str(ben), "return_start_date": "", "return_end_date": ""})

    assert response.headers["Location"].endswith(f"/lessons?start_date=&end_date=&student_id={ben}")
