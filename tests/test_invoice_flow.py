"""Invoices made from the register: drafts, what's on them, the email and PDF, and what happens after sending."""
import json
import os
from datetime import datetime
from io import BytesIO

import pytest
from pypdf import PdfReader

from helpers import draft_for, page, weekly

FETCH = {"X-Requested-With": "fetch"}


@pytest.fixture(autouse=True)
def after_term3(today):
    today("2026-09-28")


def make_drafts(client, term, **options):
    return client.post("/invoices/make", data={"term": term["id"], **options}, follow_redirects=True).get_data(as_text=True)


def invoice(db, invoice_id):
    return db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()


def pdf_text(source):
    return "\n".join(p.extract_text() for p in PdfReader(source).pages)


def table(html):
    """Just the list of invoices, not the forms around it."""
    return html.split("<table", 1)[1].split("</table>", 1)[0] if "<table" in html else ""


@pytest.fixture
def alice(db, student, lesson):
    """Alice (whose mum Pat pays): three Monday lessons in Term 3, the second one cancelled."""
    sid = student("Alice Aroha", "pat@example.com", parent="Pat Aroha")
    ids = weekly(lesson, sid, weeks=3, minutes=30, rate=70)
    db.execute("UPDATE lessons SET status='cancelled' WHERE id=?", (ids[1],))
    db.commit()
    return sid


@pytest.fixture
def alices_draft(client, db, term3, alice):
    make_drafts(client, term3)
    return draft_for(db, alice)["id"]


@pytest.fixture
def sent(client, db, alices_draft, gmail):
    client.post(f"/invoices/{alices_draft}/send", headers=FETCH)
    return alices_draft


# ---------------------------------------------------------------- making drafts

def test_drafts_are_made_from_the_register_and_nothing_is_emailed(client, db, term3, alice, student, lesson, gmail):
    ben = student("Ben Brown")
    lesson(ben, "2026-08-04 16:00", minutes=45, rate=60, status="missed")
    student("Carl Chen")                                                   # no lessons, no invoice

    ask = page(client, f"/invoices/make?term={term3['id']}")
    assert "2 students have lessons to invoice" in ask and "Alice Aroha, Ben Brown" in ask

    done = make_drafts(client, term3)

    assert "2 draft invoices made. Nothing has been emailed yet" in done
    assert gmail.outbox == []
    rows = db.execute("SELECT * FROM invoices ORDER BY id").fetchall()
    assert [(r["student_id"], r["status"], r["total_cents"]) for r in rows] == [(alice, "draft", 7000), (ben, "draft", 4500)]
    assert [r["invoice_number"] for r in rows] == [f"INV{datetime.now():%y}-{r['id']:04d}" for r in rows]
    assert db.execute("SELECT COUNT(*) FROM lessons WHERE invoice_id=?", (rows[0]["id"],)).fetchone()[0] == 3
    assert 'data-ids="1,2"' in done and "Send 2 drafts" in done
    assert "There was nothing new to invoice" in make_drafts(client, term3)


def test_a_family_can_have_one_invoice(client, db, term3, student, lesson):
    alice = student("Alice Aroha", "pat@example.com")
    ben = student("Ben Aroha", "PAT@example.com ")
    lesson(alice, "2026-07-20 15:30")
    lesson(ben, "2026-07-20 16:00")
    assert "Alice Aroha and Ben Aroha" in page(client, f"/invoices/make?term={term3['id']}")

    make_drafts(client, term3, family="1")

    inv = db.execute("SELECT * FROM invoices").fetchone()
    html = page(client, f"/invoices/{inv['id']}")
    assert "Alice: Lesson, Mon 20 Jul, 3:30 pm (30 min)" in html and "Ben: Lesson, Mon 20 Jul, 4:00 pm (30 min)" in html
    assert "Particulars: <b>Aroha family</b>" in html
    email = page(client, f"/invoices/{inv['id']}?tab=email")
    assert "Here is the invoice for Alice and Ben’s cello lessons in Term 3 (20 Jul to 25 Sep)." in email


def test_amounts_owing_are_added_only_when_asked(client, db, term3, alice, make_invoice):
    old = make_invoice(alice, status="sent", total=300, emailed_at="2026-06-30 09:00:00")
    ask = page(client, f"/invoices/make?term={term3['id']}")
    assert "Add what’s still owing from earlier invoices" in ask and "$300.00" in ask

    make_drafts(client, term3)
    first = draft_for(db, alice)
    assert first["total_cents"] == 7000 and invoice(db, old)["status"] == "sent"

    client.post(f"/invoices/{first['id']}/delete")
    make_drafts(client, term3, carry="1")

    draft = draft_for(db, alice)
    assert draft["total_cents"] == 37000
    assert f"Still owing from {invoice(db, old)['invoice_number']}" in page(client, f"/invoices/{draft['id']}")
    assert (invoice(db, old)["status"], invoice(db, old)["carried_to"]) == ("carried", draft["id"])


def test_lessons_an_older_invoice_covered_can_be_billed_on_the_term_instead(client, db, term3, alice, make_invoice):
    old = make_invoice(alice, status="sent", emailed_at="2026-06-30 09:00:00")
    db.execute("UPDATE lessons SET invoice_id=?", (old,))       # how the upgrade links an invoice's lessons by its dates
    db.commit()

    ask = page(client, f"/invoices/make?term={term3['id']}")
    assert "Some Term 3 2026 lessons are already on an older invoice" in ask
    assert f"3 lessons on {invoice(db, old)['invoice_number']} (20 Jul to 25 September 2026)" in ask
    assert "There’s nothing new to invoice" in ask

    client.post("/invoices/make/release", data={"term": term3["id"], "invoice": old})
    make_drafts(client, term3)

    assert draft_for(db, alice)["total_cents"] == 7000
    assert "will be billed on Term 3 2026 invoices instead" in page(client, f"/invoices/{old}?tab=history")


# ---------------------------------------------------------------- one invoice

def test_the_invoice_shows_its_lines_from_the_register(client, db, term3, student, lesson):
    ben = student("Ben Brown", parent="")
    lesson(ben, "2026-07-21 16:00", minutes=45, rate=60)
    lesson(ben, "2026-07-28 16:00", minutes=45, rate=60, status="cancelled")
    lesson(ben, "2026-08-04 16:00", minutes=45, rate=60, status="missed")
    lesson(ben, "2026-08-11 16:00", minutes=45, rate=60, status="holiday")
    extra = lesson(ben, "2026-08-14 10:00", minutes=30, rate=60, kind="extra", note="makeup for 28 Jul")
    make_drafts(client, term3)

    html = page(client, f"/invoices/{draft_for(db, ben)['id']}")

    assert "Lesson, Tue 21 Jul, 4:00 pm (45 min)" in html
    assert "Cancelled, Tue 28 Jul" in html and "no charge" in html
    assert "Missed lesson, Tue 4 Aug, 4:00 pm (45 min)" in html
    assert "Tue 11 Aug" not in html                                            # holidays aren't on it
    assert "Extra lesson, Fri 14 Aug, 10:00 am (30 min), makeup for 28 Jul" in html
    assert f"/register?term={term3['id']}&amp;week=4#lesson-{extra}" in html
    assert "$120.00" in html                                                   # 45 + 45 + 30 at $60 an hour


def test_items_and_discounts_can_be_added_and_removed(client, db, alices_draft):
    client.post(f"/invoices/{alices_draft}/items", data={"description": "ABRSM Grade 5 exam entry", "amount": "120"})
    client.post(f"/invoices/{alices_draft}/items", data={"description": "Sibling discount", "amount": "−20"})

    html = page(client, f"/invoices/{alices_draft}")
    assert "ABRSM Grade 5 exam entry" in html and "−$20.00" in html
    assert invoice(db, alices_draft)["total_cents"] == 7000 + 12000 - 2000

    item = db.execute("SELECT id FROM invoice_items WHERE description='Sibling discount'").fetchone()[0]
    client.post(f"/invoices/{alices_draft}/items/{item}/delete")
    assert invoice(db, alices_draft)["total_cents"] == 19000


@pytest.mark.parametrize("description, amount", [("Exam fee", "twelve"), ("Exam fee", "0"), ("", "20"), ("Exam fee", "inf")])
def test_an_item_that_cannot_be_read_is_not_added(client, db, alices_draft, description, amount):
    html = client.post(f"/invoices/{alices_draft}/items", data={"description": description, "amount": amount},
                       follow_redirects=True).get_data(as_text=True)

    assert "Type what it’s for and an amount" in html
    assert db.execute("SELECT COUNT(*) FROM invoice_items").fetchone()[0] == 0


def test_the_standard_email(client, db, alices_draft):
    number = invoice(db, alices_draft)["invoice_number"]

    html = page(client, f"/invoices/{alices_draft}?tab=email")

    for text in ["Kia ora Pat,", "Here is the invoice for Alice’s cello lessons in Term 3 (20 Jul to 25 Sep).",
                 "Total: $70.00. Prompt payment is appreciated.", f"Reference: {number}", "Particulars: Alice Aroha",
                 "Ngā mihi,", f"Cello lessons, Term 3 2026 – Alice Aroha ({number})"]:
        assert text in html


def test_someone_paying_for_their_own_lessons_gets_your_invoice(client, db, term3, student, lesson):
    sid = student("Alice Aroha", parent="")
    lesson(sid)
    make_drafts(client, term3)

    html = page(client, f"/invoices/{draft_for(db, sid)['id']}?tab=email")

    assert "Kia ora Alice," in html and "Here is your invoice for cello lessons in Term 3 (20 Jul to 25 Sep)." in html


def test_the_email_wording_can_be_changed_for_one_invoice(client, db, alices_draft, gmail):
    client.post(f"/invoices/{alices_draft}/email", data={"subject": "Term 3 lessons", "body": "Hi Pat, here it is."})

    assert "Uses your own wording" in page(client, f"/invoices/{alices_draft}?tab=email")
    client.post(f"/invoices/{alices_draft}/send", headers=FETCH)
    assert (gmail.outbox[0]["subject"], gmail.outbox[0]["body_text"]) == ("Term 3 lessons", "Hi Pat, here it is.")
    assert "Hi Pat, here it is." in page(client, f"/invoices/{alices_draft}?tab=email")


def test_the_standard_wording_can_be_put_back(client, db, alices_draft):
    client.post(f"/invoices/{alices_draft}/email", data={"subject": "Mine", "body": "Mine"})

    client.post(f"/invoices/{alices_draft}/email", data={"action": "reset"})

    assert tuple(db.execute("SELECT email_subject, email_body FROM invoices").fetchone()) == (None, None)


def test_the_pdf_has_the_logo_lines_and_how_to_pay(client, db, app, alices_draft):
    number = invoice(db, alices_draft)["invoice_number"]

    response = client.get(f"/invoices/{alices_draft}/pdf")

    assert response.mimetype == "application/pdf"
    text = pdf_text(BytesIO(response.data))
    for line in ["Lesson, Mon 20 Jul, 3:30 pm (30 min)", "Cancelled, Mon 27 Jul", "no charge", "Total", "$70.00",
                 "Prompt payment is appreciated.", f"Reference: {number}", "Particulars: Alice Aroha", "BILL TO", "Pat Aroha"]:
        assert line in text
    assert len(PdfReader(BytesIO(response.data)).pages[0].images) == 1         # the logo
    assert os.listdir(app.config["INVOICE_PDF_DIR"]) == []                     # a draft's PDF isn't kept


def test_names_with_symbols_appear_in_the_pdf_as_typed(client, db, app, term3, student, lesson):
    sid = student("Tom & Jerry <Junior>", parent="")
    lesson(sid)
    make_drafts(client, term3)
    draft = draft_for(db, sid)["id"]
    client.post(f"/invoices/{draft}/items", data={"description": "Strings <A & D>", "amount": "30"})

    client.post(f"/invoices/{draft}/mark-sent")

    text = pdf_text(os.path.join(app.config["INVOICE_PDF_DIR"], invoice(db, draft)["pdf_filename"]))
    assert "Tom & Jerry <Junior>" in text and "Strings <A & D>" in text


def test_a_one_off_invoice_leaves_the_lessons_for_the_term_invoice(client, db, term3, student, lesson):
    sid = student("Alice Aroha", parent="")
    lesson(sid)

    response = client.post("/invoices/new", data={"student_id": sid, "term": term3["id"]})

    inv = db.execute("SELECT * FROM invoices").fetchone()
    assert response.headers["Location"].endswith(f"/invoices/{inv['id']}")
    client.post(f"/invoices/{inv['id']}/items", data={"description": "Exam entry", "amount": "95"})
    assert "Here is an invoice for you." in page(client, f"/invoices/{inv['id']}?tab=email")
    assert invoice(db, inv["id"])["total_cents"] == 9500
    assert db.execute("SELECT invoice_id FROM lessons").fetchone()[0] is None
    make_drafts(client, term3)
    assert db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 2


def test_a_draft_can_be_deleted_and_its_lessons_billed_again(client, db, term3, alice, alices_draft):
    response = client.post(f"/invoices/{alices_draft}/delete", follow_redirects=True)

    assert "deleted" in response.get_data(as_text=True)
    assert db.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM lessons WHERE invoice_id IS NULL").fetchone()[0] == 3


def test_a_sent_invoice_cannot_be_deleted_or_changed(client, db, sent):
    client.post(f"/invoices/{sent}/delete")
    html = client.post(f"/invoices/{sent}/items", data={"description": "Extra", "amount": "10"}, follow_redirects=True).get_data(as_text=True)

    assert invoice(db, sent)["status"] == "sent"
    assert "Use “Correct and resend” to change it" in html


# ---------------------------------------------------------------- payments

def test_payments_part_then_full(client, db, sent):
    html = client.post(f"/invoices/{sent}/payments", data={"amount": "30.00", "paid_on": "2026-10-01", "reference": "ALICE"},
                       follow_redirects=True).get_data(as_text=True)
    assert "Payment saved. $40.00 still to pay." in html and "Part paid" in html
    assert tuple(db.execute("SELECT status, paid_amount, paid_at, paid_ref FROM invoices").fetchone()) == ("sent", 30.0, "2026-10-01 00:00", "ALICE")

    html = client.post(f"/invoices/{sent}/payments", data={"amount": "40", "paid_on": "2026-10-03"}, follow_redirects=True).get_data(as_text=True)
    assert "It’s paid in full" in html
    assert invoice(db, sent)["status"] == "paid"


@pytest.mark.parametrize("amount, paid_on, message", [("inf", "2026-10-01", "Type the amount received"), ("", "2026-10-01", "Type the amount"),
                                                      ("-5", "2026-10-01", "Type the amount"), ("70", "next Tuesday", "date wasn’t understood")])
def test_a_payment_that_cannot_be_read_is_not_saved(client, db, sent, amount, paid_on, message):
    html = client.post(f"/invoices/{sent}/payments", data={"amount": amount, "paid_on": paid_on}, follow_redirects=True).get_data(as_text=True)

    assert message in html
    assert db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


def test_a_payment_can_be_removed(client, db, sent):
    client.post(f"/invoices/{sent}/payments", data={"amount": "70", "paid_on": "2026-10-01"})
    payment = db.execute("SELECT id FROM payments").fetchone()[0]

    client.post(f"/invoices/{sent}/payments/{payment}/delete")

    assert tuple(db.execute("SELECT status, paid_amount, paid_at FROM invoices").fetchone()) == ("sent", None, None)


# ---------------------------------------------------------------- when it isn't paid

def test_what_is_owing_moves_to_the_next_terms_invoice(client, db, term4, sent, alice, lesson):
    client.post(f"/invoices/{sent}/payments", data={"amount": "20", "paid_on": "2026-10-01"})

    client.post(f"/invoices/{sent}/move")
    assert (invoice(db, sent)["status"], invoice(db, sent)["carried_to"]) == ("carried", None)
    lesson(alice, "2026-10-12 15:30")
    make_drafts(client, term4)                                               # without asking to add amounts owing

    draft = draft_for(db, alice)
    assert draft["total_cents"] == 3500 + 5000
    assert invoice(db, sent)["carried_to"] == draft["id"]
    assert "Moved to " + draft["invoice_number"] in page(client, f"/invoices/{sent}")


def test_what_is_owing_goes_straight_onto_a_draft_already_made(client, db, term3, alice, make_invoice):
    old = make_invoice(alice, status="sent", total=300, emailed_at="2026-06-30 09:00:00")
    make_drafts(client, term3)
    draft = draft_for(db, alice)

    html = client.post(f"/invoices/{old}/move", follow_redirects=True).get_data(as_text=True)

    assert f"The amount still owing is now on draft {draft['invoice_number']}" in html
    assert invoice(db, draft["id"])["total_cents"] == 7000 + 30000

    client.post(f"/invoices/{old}/undo")                                     # changed their mind
    assert invoice(db, old)["status"] == "sent" and invoice(db, draft["id"])["total_cents"] == 7000


def test_an_amount_already_on_a_sent_invoice_cannot_be_undone(client, db, term3, alice, make_invoice, gmail):
    old = make_invoice(alice, status="sent", total=300, emailed_at="2026-06-30 09:00:00")
    make_drafts(client, term3, carry="1")
    client.post(f"/invoices/{draft_for(db, alice)['id']}/send")

    html = client.post(f"/invoices/{old}/undo", follow_redirects=True).get_data(as_text=True)

    assert "which has been sent" in html and invoice(db, old)["status"] == "carried"


def test_writing_off_and_undoing_it(client, db, sent):
    client.post(f"/invoices/{sent}/write-off", data={"reason": "Family moved away"})

    assert (invoice(db, sent)["status"], invoice(db, sent)["write_off_reason"]) == ("written_off", "Family moved away")
    assert table(page(client, "/invoices?show=unpaid")) == ""

    client.post(f"/invoices/{sent}/undo")
    assert invoice(db, sent)["status"] == "sent"


def test_voiding_frees_its_lessons_and_undo_takes_them_back(client, db, sent):
    client.post(f"/invoices/{sent}/void", data={"reason": "Sent to the wrong family"})

    assert invoice(db, sent)["status"] == "void"
    assert db.execute("SELECT COUNT(*) FROM lessons WHERE invoice_id IS NULL").fetchone()[0] == 3

    client.post(f"/invoices/{sent}/undo")
    assert invoice(db, sent)["status"] == "sent"
    assert db.execute("SELECT COUNT(*) FROM lessons WHERE invoice_id=?", (sent,)).fetchone()[0] == 3


# ---------------------------------------------------------------- correcting a sent invoice

def test_a_change_in_the_register_after_sending_is_pointed_out(client, db, term3, sent):
    lesson_id = db.execute("SELECT id FROM lessons ORDER BY lesson_time").fetchone()[0]
    client.post(f"/register/lesson/{lesson_id}/status", data={"status": "cancelled"}, headers=FETCH)

    html = page(client, f"/invoices/{sent}")

    assert "The register changed after this invoice was sent." in html
    assert "Mon 20 Jul is now cancelled, no charge (was a lesson)" in html
    assert invoice(db, sent)["total_cents"] == 7000                           # the invoice as sent


def test_correct_and_resend(client, db, app, sent, gmail):
    lesson_id = db.execute("SELECT id FROM lessons ORDER BY lesson_time").fetchone()[0]
    client.post(f"/register/lesson/{lesson_id}/status", data={"status": "cancelled"}, headers=FETCH)

    client.post(f"/invoices/{sent}/correct")
    assert (invoice(db, sent)["status"], invoice(db, sent)["revision"]) == ("revising", 2)
    assert "You’re correcting this invoice." in page(client, f"/invoices/{sent}")

    result = client.post(f"/invoices/{sent}/send", headers=FETCH).get_json()

    number = invoice(db, sent)["invoice_number"]
    assert result["status"] == "sent"
    assert gmail.outbox[-1]["subject"].startswith("Corrected: ")
    assert "This corrected invoice replaces the one I sent earlier." in gmail.outbox[-1]["body_text"]
    assert gmail.outbox[-1]["pdf_fullpath"].endswith(f"{number}-v2.pdf")
    assert "Corrected invoice (version 2)" in pdf_text(gmail.outbox[-1]["pdf_fullpath"])
    assert (invoice(db, sent)["status"], invoice(db, sent)["total_cents"]) == ("sent", 3500)
    versions = db.execute("SELECT revision, total_cents FROM invoice_versions ORDER BY revision").fetchall()
    assert [tuple(v) for v in versions] == [(1, 7000), (2, 3500)]


def test_a_correction_can_be_cancelled(client, db, sent):
    client.post(f"/invoices/{sent}/correct")
    client.post(f"/invoices/{sent}/items", data={"description": "Exam entry", "amount": "95"})

    client.post(f"/invoices/{sent}/correct/cancel")

    assert (invoice(db, sent)["status"], invoice(db, sent)["revision"], invoice(db, sent)["total_cents"]) == ("sent", 1, 7000)
    assert db.execute("SELECT COUNT(*) FROM invoice_items").fetchone()[0] == 0


def test_history_keeps_what_was_sent(client, db, sent):
    html = page(client, f"/invoices/{sent}?tab=history")

    assert "Version 1, $70.00, emailed to pat@example.com" in html
    assert "Draft made from the register" in html
    lines = json.loads(db.execute("SELECT lines_json FROM invoice_versions").fetchone()[0])
    assert [line["kind"] for line in lines] == ["lesson", "cancelled", "lesson"]


# ---------------------------------------------------------------- the lists

def test_the_invoice_lists(client, db, term3, sent, student, lesson, make_invoice):
    ben = student("Ben Brown")
    lesson(ben, "2026-07-22 10:00", kind="extra")
    make_drafts(client, term3)
    old_void = make_invoice(student("Carl Chen"), status="void")

    term_list = page(client, f"/invoices?term={term3['id']}")
    assert "Alice Aroha" in table(term_list) and "Ben Brown" in table(term_list) and "Extras $35.00" in table(term_list)
    assert "Send 1 draft" in term_list
    unpaid = table(page(client, "/invoices?show=unpaid"))
    assert "Alice Aroha" in unpaid and "Ben Brown" not in unpaid
    assert invoice(db, old_void)["invoice_number"] in table(page(client, "/invoices?show=all"))
    bens = table(page(client, f"/invoices?student_id={ben}"))
    assert "Ben Brown" in bens and "Alice Aroha" not in bens
    assert client.get("/invoices/list").status_code == 301


def test_invoices_from_before_terms_still_show_and_open(client, db, app, student, make_invoice):
    old = make_invoice(student(), status="paid", paid_amount=300, emailed_at="2026-06-30 09:00:00")
    number = invoice(db, old)["invoice_number"]
    with open(os.path.join(app.config["INVOICE_PDF_DIR"], f"{number}.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 test")

    assert number in page(client, "/invoices?show=all")
    html = page(client, f"/invoices/{old}")
    assert "only its total ($300.00) is kept" in html and "Paid" in html
    assert client.get(f"/invoices/{old}/pdf").status_code == 200
    assert "before the app kept a copy of each email" in page(client, f"/invoices/{old}?tab=email")
