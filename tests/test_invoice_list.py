import re

import pytest

import routes.invoices


@pytest.fixture
def invoices_of_each_status(make_student, make_invoice):
    alice = make_student()
    return {
        "draft": make_invoice(alice, status="draft"),
        "sent": make_invoice(alice, status="sent", emailed_at="2026-07-18 09:00:00"),
        "paid": make_invoice(alice, status="paid", emailed_at="2026-07-18 09:00:00", paid_amount=300),
        "void": make_invoice(alice, status="void"),
    }


def list_page(client, query=""):
    return client.get(f"/invoices/list{query}").get_data(as_text=True)


def status_of(db, invoice_id):
    return db.execute("SELECT status FROM invoices WHERE id=?", (invoice_id,)).fetchone()["status"]


def test_no_form_is_nested_inside_the_bulk_send_form(client, invoices_of_each_status):
    # Browsers drop the first nested <form>, which made "Mark sent" on the top row do nothing.
    html = list_page(client)
    start = html.index('id="bulk-send-form"')
    end = html.index("</form>", start)
    assert "<form" not in html[start:end]


def test_mark_sent_buttons_submit_their_own_form(client, invoices_of_each_status):
    html = list_page(client)
    draft = invoices_of_each_status["draft"]
    assert f'form="mark-sent-{draft}"' in html
    assert f'<form id="mark-sent-{draft}"' in html


def test_row_action_forms_return_to_the_same_filtered_list(client, invoices_of_each_status):
    draft = invoices_of_each_status["draft"]
    html = list_page(client, "?status=draft&term=T3")
    form = html[html.index(f'<form id="mark-sent-{draft}"'):]
    form = form[:form.index("</form>")]
    assert 'name="return_status" value="draft"' in form
    assert 'name="return_term" value="T3"' in form


def test_mark_sent(client, db, invoices_of_each_status):
    draft = invoices_of_each_status["draft"]
    client.post(f"/invoices/status/{draft}", data={"status": "sent"})
    assert status_of(db, draft) == "sent"


def test_action_menus_are_positioned_so_the_table_does_not_clip_them(client, invoices_of_each_status):
    html = list_page(client)
    toggles = re.findall(r'<button[^>]*data-bs-toggle="dropdown"[^>]*>', html)
    assert len(toggles) == 4
    assert all("data-bs-popper-config='{\"strategy\":\"fixed\"}'" in t for t in toggles)


def test_paid_and_void_invoices_cannot_be_selected_for_sending(client, invoices_of_each_status):
    html = list_page(client)
    for status, invoice_id in invoices_of_each_status.items():
        box = re.search(rf'<input type="checkbox" name="invoice_id" value="{invoice_id}"[^>]*>', html).group(0)
        assert ("disabled" in box) == (status in ("paid", "void")), status


def test_bulk_send_skips_paid_and_void_invoices(client, db, invoices_of_each_status, monkeypatch):
    emailed = []

    def fake_send(inv, pdf_path, fmt_date, parse_date_any):
        emailed.append(inv["id"])
        return {"status": "sent", "to": inv["student_email"]}

    monkeypatch.setattr(routes.invoices, "send_invoice", fake_send)
    ids = invoices_of_each_status

    page = client.post("/invoices/list", data={
        "action": "send", "confirm_send": "1", "invoice_id": [str(i) for i in ids.values()],
    }, follow_redirects=True).get_data(as_text=True)

    assert sorted(emailed) == sorted([ids["draft"], ids["sent"]])
    assert status_of(db, ids["paid"]) == "paid"
    assert status_of(db, ids["void"]) == "void"
    assert "Emailed: 2, Not sent: 2" in page


def test_void_an_invoice_keeps_the_list_filters(client, db, invoices_of_each_status):
    draft = invoices_of_each_status["draft"]

    resp = client.post(f"/invoices/void/{draft}", data={
        "void_reason": "Replaced by INV-2026-0113", "return_status": "draft", "return_term": "T3",
    })

    assert resp.status_code == 302
    assert "status=draft" in resp.location and "term=T3" in resp.location
    row = db.execute("SELECT status, voided_at, void_reason FROM invoices WHERE id=?", (draft,)).fetchone()
    assert row["status"] == "void"
    assert row["voided_at"]
    assert row["void_reason"] == "Replaced by INV-2026-0113"


def test_paid_invoices_cannot_be_voided(client, db, invoices_of_each_status):
    paid = invoices_of_each_status["paid"]
    client.post(f"/invoices/void/{paid}", data={})
    assert status_of(db, paid) == "paid"


@pytest.mark.parametrize("emailed_at, expected", [(None, "draft"), ("2026-07-18 09:00:00", "sent")])
def test_restore_puts_a_void_invoice_back(client, db, make_student, make_invoice, emailed_at, expected):
    invoice = make_invoice(make_student(), status="void", emailed_at=emailed_at)
    db.execute("UPDATE invoices SET voided_at='2026-09-27 10:00', void_reason='oops' WHERE id=?", (invoice,))
    db.commit()

    client.post(f"/invoices/restore/{invoice}", data={})

    row = db.execute("SELECT status, voided_at, void_reason FROM invoices WHERE id=?", (invoice,)).fetchone()
    assert tuple(row) == (expected, None, None)


def test_a_void_invoice_cannot_be_marked_paid(client, db, invoices_of_each_status):
    void = invoices_of_each_status["void"]
    client.post(f"/invoices/status/{void}", data={"status": "paid", "paid_amount": "300"})
    assert status_of(db, void) == "void"


def test_void_invoices_are_labelled_and_offer_restore_not_mark_paid(client, invoices_of_each_status):
    html = list_page(client, "?status=void")
    rows = html.count('name="invoice_id"')
    assert rows == 1
    assert re.search(r"</i>\s*Void\s*</span>", html)
    assert "Restore" in html
    assert "Mark paid" not in html
