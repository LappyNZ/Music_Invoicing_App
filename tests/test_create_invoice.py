from html.parser import HTMLParser

import pytest

TERM = dict(start_date="2026-07-20", end_date="2026-09-25")


class _FormFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and a.get("name"):
            self.fields[a["name"]] = a.get("value") or ""


def form_fields(html):
    """The inputs a browser would send back from the page, by name."""
    parser = _FormFields()
    parser.feed(html)
    return parser.fields


def durations(html):
    fields = form_fields(html)
    return [v for k, v in sorted(fields.items()) if k.startswith("lesson_duration_")]


def invoice_totals(db):
    return [r["total"] for r in db.execute("SELECT total FROM invoices ORDER BY id")]


@pytest.fixture
def alice_and_ben(make_student, make_lesson):
    """Alice has three 30-minute lessons, Ben three 45-minute ones, all at $60/h."""
    alice = make_student("Alice Aroha", "alice@example.com")
    ben = make_student("Ben Brown", "ben@example.com", parent="")
    for day in ("2026-07-20", "2026-07-27", "2026-08-03"):
        make_lesson(alice, f"{day} 15:00", duration=30)
        make_lesson(ben, f"{day} 16:00", duration=45)
    return alice, ben


def preview(client, student_id, **fields):
    return client.post("/invoices", data={"action": "preview", "student_id": student_id, **TERM, **fields})


def resubmit(client, page, action, **changes):
    """Press a button on a previewed page, after editing some fields."""
    data = form_fields(page.get_data(as_text=True))
    data.update(action=action, **TERM)
    data.update(changes)
    return client.post("/invoices", data=data)


def test_switching_student_then_preview_loads_the_new_students_lessons(client, alice_and_ben):
    alice, ben = alice_and_ben
    page = preview(client, alice)
    assert durations(page.get_data(as_text=True)) == ["30", "30", "30"]

    page = resubmit(client, page, "preview", student_id=ben)

    html = page.get_data(as_text=True)
    assert durations(html) == ["45", "45", "45"]
    assert "reloaded" in html


def test_generate_after_switching_student_does_not_bill_the_old_lessons(client, db, alice_and_ben):
    alice, ben = alice_and_ben
    page = preview(client, alice)

    page = resubmit(client, page, "generate_pdf", student_id=ben)

    assert invoice_totals(db) == []
    html = page.get_data(as_text=True)
    assert "Not generated" in html
    assert durations(html) == ["45", "45", "45"]


def test_preview_again_keeps_edits_for_the_same_student(client, alice_and_ben):
    alice, _ = alice_and_ben
    page = preview(client, alice)

    page = resubmit(client, page, "preview", student_id=alice, lesson_duration_1="20")

    assert durations(page.get_data(as_text=True)) == ["20", "30", "30"]


def test_extra_items_survive_a_second_preview(client, alice_and_ben):
    alice, _ = alice_and_ben
    page = preview(client, alice)

    page = resubmit(client, page, "preview", student_id=alice, extra_desc_1="Exam fee", extra_price_1="95")

    fields = form_fields(page.get_data(as_text=True))
    assert fields["extra_desc_1"] == "Exam fee"
    assert fields["extra_price_1"] == "95.00"


def test_generate_bills_lessons_and_extras(client, db, alice_and_ben):
    alice, _ = alice_and_ben
    page = preview(client, alice)

    resubmit(client, page, "generate_pdf", student_id=alice, extra_desc_1="Exam fee", extra_price_1="95")

    assert invoice_totals(db) == [pytest.approx(3 * 30.0 + 95)]


def test_deleting_every_lesson_row_is_respected(client, db, alice_and_ben):
    alice, _ = alice_and_ben
    page = preview(client, alice)
    data = {k: v for k, v in form_fields(page.get_data(as_text=True)).items() if not k.startswith("lesson_")}
    data.update(action="generate_pdf", student_id=alice, lesson_count="0",
                extra_desc_1="Cello hire", extra_price_1="50", **TERM)

    client.post("/invoices", data=data)

    assert invoice_totals(db) == [pytest.approx(50.0)]


def test_student_without_lessons_gets_a_message_and_can_still_have_extras(client, db, make_student):
    carl = make_student("Carl Chen", "carl@example.com")

    page = preview(client, carl)
    html = page.get_data(as_text=True)
    assert "No lessons found" in html
    assert "extra_desc_1" in form_fields(html)

    page = resubmit(client, page, "generate_pdf", student_id=carl)
    assert invoice_totals(db) == []
    assert "nothing to invoice" in page.get_data(as_text=True)

    resubmit(client, page, "generate_pdf", student_id=carl, extra_desc_1="Cello hire", extra_price_1="50")
    assert invoice_totals(db) == [pytest.approx(50.0)]


def test_lesson_time_edited_with_a_T_does_not_crash_the_preview(client, make_student, make_lesson):
    dana = make_student("Dana Dunn", "dana@example.com")
    make_lesson(dana, "2026-07-21T15:30")

    page = preview(client, dana)

    assert page.status_code == 200
    shown = form_fields(page.get_data(as_text=True))["lesson_date_1"]
    assert "21 Jul 26" in shown and "3:30PM" in shown  # Windows shows 03:30PM


def test_generate_without_previewing_first_still_works(client, db, alice_and_ben):
    alice, _ = alice_and_ben

    client.post("/invoices", data={"action": "generate_pdf", "student_id": alice, **TERM})

    assert invoice_totals(db) == [pytest.approx(90.0)]
