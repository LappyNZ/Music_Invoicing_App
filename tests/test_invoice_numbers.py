import os
from datetime import datetime

import pytest
from pypdf import PdfReader

from services import invoice_service

TERM = dict(start_date="2026-07-20", end_date="2026-09-25")


@pytest.fixture
def alice(make_student, make_lesson):
    student = make_student("Alice Aroha", "pat@example.com", parent="Pat Aroha")
    make_lesson(student, "2026-07-20 15:00", duration=30)
    return student


def generate(client, student_id):
    return client.post("/invoices", data={"action": "generate_pdf", "student_id": student_id, **TERM})


def only_invoice(db):
    return db.execute("SELECT id, invoice_number, pdf_filename FROM invoices").fetchone()


def test_new_invoices_get_a_short_number_and_a_pdf_named_after_it(client, db, app, alice):
    generate(client, alice)

    row = only_invoice(db)
    expected = f"INV{datetime.now():%y}-{row['id']:04d}"
    assert (row["invoice_number"], row["pdf_filename"]) == (expected, f"{expected}.pdf")
    assert len(expected) <= 12  # fits a NZ bank payment's Reference field
    assert os.path.exists(os.path.join(app.config["INVOICE_PDF_DIR"], f"{expected}.pdf"))
    assert expected in client.get("/invoices/list").get_data(as_text=True)
    assert client.get(f"/invoices/pdf/{row['id']}").status_code == 200


def test_invoices_from_before_numbers_were_stored_still_show_and_open(client, db, app, make_student, make_invoice):
    invoice = make_invoice(make_student())
    created = db.execute("SELECT created_at FROM invoices WHERE id=?", (invoice,)).fetchone()[0]
    old_number = f"INV-{created[:4]}-{invoice:04d}"
    with open(os.path.join(app.config["INVOICE_PDF_DIR"], f"{old_number}.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 test")

    assert old_number in client.get("/invoices/list").get_data(as_text=True)
    assert client.get(f"/invoices/pdf/{invoice}").status_code == 200


def test_email_and_pdf_ask_for_the_same_payment_reference(client, db, app, alice, monkeypatch):
    generate(client, alice)
    row = only_invoice(db)
    reader = PdfReader(os.path.join(app.config["INVOICE_PDF_DIR"], row["pdf_filename"]))
    pdf_text = reader.pages[0].extract_text()
    assert f"Reference: {row['invoice_number']}" in pdf_text
    assert "Particulars: Alice Aroha" in pdf_text

    sent = {}

    def fake_gmail(**message):
        sent.update(message)
        return {"status": "sent", "to": message["to_email"]}

    monkeypatch.setattr(invoice_service, "send_invoice_via_gmail", fake_gmail)
    client.post("/invoices/list", data={"action": "send", "confirm_send": "1", "invoice_id": str(row["id"])})

    assert f"Reference: {row['invoice_number']}" in sent["body_text"]
    assert "Particulars: Alice Aroha" in sent["body_text"]
    assert sent["pdf_fullpath"].endswith(row["pdf_filename"])


def test_payment_date_from_the_form_is_stored_as_entered(client, db, make_student, make_invoice):
    invoice = make_invoice(make_student(), status="sent")

    client.post(f"/invoices/status/{invoice}",
                data={"status": "paid", "paid_amount": "300", "paid_at": "2026-10-01T09:30"})

    assert db.execute("SELECT paid_at FROM invoices WHERE id=?", (invoice,)).fetchone()[0] == "2026-10-01 09:30"


def test_payment_date_left_blank_is_now_in_local_time(client, db, make_student, make_invoice, new_zealand_time):
    invoice = make_invoice(make_student(), status="sent")

    client.post(f"/invoices/status/{invoice}", data={"status": "paid", "paid_amount": "300"})

    paid_at = db.execute("SELECT paid_at FROM invoices WHERE id=?", (invoice,)).fetchone()[0]
    assert abs((datetime.strptime(paid_at, "%Y-%m-%d %H:%M") - datetime.now()).total_seconds()) < 120


@pytest.mark.parametrize("field, value, message", [
    ("paid_amount", "1,200.00", "must be a number"),
    ("paid_amount", "inf", "must be a number"),
    ("paid_at", "next Tuesday", "date wasn"),
])
def test_unreadable_payment_details_change_nothing(client, db, make_student, make_invoice, field, value, message):
    invoice = make_invoice(make_student(), status="sent")

    page = client.post(f"/invoices/status/{invoice}", data={"status": "paid", field: value}, follow_redirects=True)

    assert message in page.get_data(as_text=True)
    assert db.execute("SELECT status FROM invoices WHERE id=?", (invoice,)).fetchone()[0] == "sent"


def test_created_time_is_shown_in_new_zealand_time(client, db, make_student, make_invoice, new_zealand_time):
    invoice = make_invoice(make_student())
    db.execute("UPDATE invoices SET created_at='2026-07-17 21:04:00' WHERE id=?", (invoice,))
    db.commit()

    assert "Created: 2026-07-18 09:04" in client.get("/invoices/list").get_data(as_text=True)
