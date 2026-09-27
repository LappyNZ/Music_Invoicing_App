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
