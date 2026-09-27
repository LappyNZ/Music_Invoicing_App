import os

import pytest
from pypdf import PdfReader

TERM = dict(start_date="2026-07-20", end_date="2026-09-25")


@pytest.fixture
def alice(make_student, make_lesson):
    student = make_student("Alice Aroha")
    make_lesson(student, "2026-07-20 15:00", duration=30)
    return student


def generate(client, student_id, **rows):
    data = {"action": "generate_pdf", "student_id": student_id, **TERM,
            "previewed_student_id": str(student_id), "previewed_start_date": TERM["start_date"],
            "previewed_end_date": TERM["end_date"], "lesson_count": "1", "lesson_date_1": "Mon, 20 Jul 26, 3:00PM",
            "lesson_duration_1": "30", "lesson_rate_1": "60", "extra_count": "1"}
    data.update(rows)
    return client.post("/invoices", data=data)


def invoice_count(db):
    return db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]


def test_a_start_date_after_the_end_date_is_questioned(client, db, alice):
    page = client.post("/invoices", data={"action": "preview", "student_id": alice,
                                          "start_date": "2026-09-25", "end_date": "2026-07-20"}).get_data(as_text=True)

    assert "The start date is after the end date" in page
    assert 'id="lessons-table"' not in page


@pytest.mark.parametrize("rows, message", [
    ({"extra_desc_1": "Exam fee"}, "extra item 1 needs a description and a price"),
    ({"extra_price_1": "20"}, "extra item 1 needs a description and a price"),
    ({"lesson_duration_1": "half an hour"}, "lesson 1 needs a date, and numbers for duration and rate"),
    ({"lesson_rate_1": ""}, "lesson 1 needs a date"),
    ({"lesson_duration_1": "nan"}, "lesson 1 needs a date"),
])
def test_a_half_filled_or_unreadable_row_stops_the_invoice(client, db, alice, rows, message):
    response = generate(client, alice, **rows)

    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Not generated: " + message in page
    assert "is-invalid" in page
    assert invoice_count(db) == 0
    for value in rows.values():
        assert f'value="{value}"' in page  # kept, to be fixed


def test_complete_rows_still_generate(client, db, alice):
    generate(client, alice, extra_desc_1="Exam fee", extra_price_1="20")

    assert db.execute("SELECT total FROM invoices").fetchone()[0] == 50.0


def test_names_with_symbols_appear_in_the_pdf_as_typed(client, db, app, make_student, make_lesson):
    student = make_student("Tom & Jerry <Junior>")
    make_lesson(student, "2026-07-20 15:00")

    generate(client, student, lesson_date_1="Mon, 20 Jul 26, 3:00PM", extra_desc_1="Strings <A & D>",
             extra_price_1="30")

    filename = db.execute("SELECT pdf_filename FROM invoices").fetchone()[0]
    text = PdfReader(os.path.join(app.config["INVOICE_PDF_DIR"], filename)).pages[0].extract_text()
    assert "Student: Tom & Jerry <Junior>" in text
    assert "Strings <A & D>" in text


# ---------------- Mark unpaid ----------------

def paid(db, make_student, make_invoice, emailed):
    invoice = make_invoice(make_student(), status="paid", paid_amount=300,
                           emailed_at="2026-09-01 09:00:00" if emailed else None)
    db.execute("UPDATE invoices SET paid_at='2026-09-10 10:00', paid_ref='ALICE' WHERE id=?", (invoice,))
    db.commit()
    return invoice


@pytest.mark.parametrize("emailed, back_to", [(True, "sent"), (False, "draft")])
def test_mark_unpaid_removes_the_payment(client, db, make_student, make_invoice, emailed, back_to):
    invoice = paid(db, make_student, make_invoice, emailed)

    page = client.post(f"/invoices/unpaid/{invoice}", follow_redirects=True).get_data(as_text=True)

    row = db.execute("SELECT status, paid_at, paid_amount, paid_ref FROM invoices WHERE id=?", (invoice,)).fetchone()
    assert tuple(row) == (back_to, None, None, None)
    assert "The payment removed was $300.00 on 2026-09-10 10:00 (ref ALICE)." in page


def test_mark_unpaid_is_offered_for_paid_invoices_only(client, db, make_student, make_invoice):
    invoice = paid(db, make_student, make_invoice, emailed=True)
    draft = make_invoice(make_student("Ben Brown"))

    page = client.get("/invoices/list").get_data(as_text=True)

    assert f'form="unpaid-{invoice}"' in page
    assert f'form="unpaid-{draft}"' not in page
    client.post(f"/invoices/unpaid/{draft}")
    assert db.execute("SELECT status FROM invoices WHERE id=?", (draft,)).fetchone()[0] == "draft"
