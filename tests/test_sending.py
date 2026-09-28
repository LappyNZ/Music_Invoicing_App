import json
import os
from types import SimpleNamespace

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

import gmail_auth
from helpers import draft_for, page
from services import email_service
from services.email_service import GmailNotConnected

FETCH = {"X-Requested-With": "fetch"}


@pytest.fixture(autouse=True)
def after_term3(today):
    today("2026-09-28")


@pytest.fixture
def draft(client, db, term3, student, lesson):
    """A Term 3 draft for Alice, whose mum Pat pays: two lessons, $70."""
    alice = student("Alice Aroha", "pat@example.com", parent="Pat Aroha")
    lesson(alice, "2026-07-20 15:30")
    lesson(alice, "2026-07-27 15:30")
    client.post("/invoices/make", data={"term": term3["id"]})
    return draft_for(db, alice)["id"]


def invoice(db, invoice_id):
    return db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()


def test_sending_emails_the_invoice_with_its_pdf_and_keeps_what_was_sent(client, db, app, gmail, draft):
    number = invoice(db, draft)["invoice_number"]

    result = client.post(f"/invoices/{draft}/send", headers=FETCH).get_json()

    assert result == {"status": "sent", "message": f"{number}: emailed to pat@example.com."}
    message = gmail.outbox[0]
    assert message["to_email"] == "pat@example.com"
    assert f"Reference: {number}" in message["body_text"] and "Particulars: Alice Aroha" in message["body_text"]
    assert message["pdf_fullpath"] == os.path.join(app.config["INVOICE_PDF_DIR"], f"{number}.pdf")
    assert os.path.isfile(message["pdf_fullpath"])
    row = invoice(db, draft)
    assert (row["status"], row["emailed_to"], row["pdf_filename"], row["total_cents"]) == ("sent", "pat@example.com", f"{number}.pdf", 7000)
    version = db.execute("SELECT * FROM invoice_versions").fetchone()
    assert (version["revision"], version["sent_to"], version["total_cents"], version["email_body"]) == (1, "pat@example.com", 7000, message["body_text"])


def test_the_address_older_pages_used_still_sends(client, db, gmail, draft):
    assert client.post(f"/invoices/send/{draft}", headers=FETCH).get_json()["status"] == "sent"


def test_an_invoice_is_only_sent_once(client, db, gmail, draft):
    client.post(f"/invoices/{draft}/send", headers=FETCH)

    result = client.post(f"/invoices/{draft}/send", headers=FETCH).get_json()

    assert result["status"] == "skipped" and len(gmail.outbox) == 1


@pytest.mark.parametrize("status", ["paid", "void"])
def test_paid_and_void_invoices_are_not_sent(client, db, gmail, make_student, make_invoice, status):
    old = make_invoice(make_student(), status=status)

    result = client.post(f"/invoices/{old}/send", headers=FETCH).get_json()

    assert result["status"] == "skipped" and gmail.outbox == []
    assert invoice(db, old)["status"] == status


def test_someone_with_no_email_is_skipped(client, db, gmail, draft):
    db.execute("UPDATE students SET email=''")
    db.commit()

    result = client.post(f"/invoices/{draft}/send", headers=FETCH).get_json()

    assert result["status"] == "skipped" and "has no email address" in result["message"]
    assert invoice(db, draft)["status"] == "draft"


def test_sending_stops_when_gmail_is_not_connected(client, db, gmail, draft):
    gmail.fail_with(GmailNotConnected("Gmail isn't connected to the app."))

    response = client.post(f"/invoices/{draft}/send", headers=FETCH)

    assert response.status_code == 503
    assert response.get_json()["status"] == "gmail_not_connected"
    assert "Gmail needs connecting again" in response.get_json()["message"]
    assert invoice(db, draft)["status"] == "draft"
    assert db.execute("SELECT COUNT(*) FROM invoice_versions").fetchone()[0] == 0


def test_a_failure_for_one_invoice_is_reported_and_it_stays_a_draft(client, db, gmail, draft):
    gmail.fail_with(ValueError("Invalid To header"))

    result = client.post(f"/invoices/{draft}/send", headers=FETCH).get_json()

    assert result["status"] == "failed" and "Invalid To header" in result["message"]
    assert invoice(db, draft)["status"] == "draft"


def test_email_switched_off_is_reported(client, db, draft):   # the tests run with EMAIL_ENABLED=0
    result = client.post(f"/invoices/{draft}/send", headers=FETCH).get_json()

    assert result["status"] == "blocked" and "switched off" in result["message"]
    assert invoice(db, draft)["status"] == "draft"


def test_without_javascript_sending_returns_to_the_invoice(client, db, gmail, draft):
    response = client.post(f"/invoices/{draft}/send")

    assert response.headers["Location"].endswith(f"/invoices/{draft}")
    assert invoice(db, draft)["status"] == "sent"


def test_a_copy_can_be_emailed_to_the_teacher_first(client, db, app, gmail, draft):
    html = client.post(f"/invoices/{draft}/test-copy", follow_redirects=True).get_data(as_text=True)

    assert "A copy was emailed to teacher@example.com. The family hasn’t been sent anything." in html
    assert gmail.outbox[0]["to_email"] == "teacher@example.com"
    assert gmail.outbox[0]["subject"].startswith("[Test copy] Cello lessons")
    assert invoice(db, draft)["status"] == "draft"
    assert os.listdir(app.config["INVOICE_PDF_DIR"]) == []


def test_marking_as_sent_emails_nobody(client, db, app, gmail, draft):
    client.post(f"/invoices/{draft}/mark-sent")

    row = invoice(db, draft)
    assert gmail.outbox == [] and row["status"] == "sent" and row["emailed_to"] is None
    assert os.path.isfile(os.path.join(app.config["INVOICE_PDF_DIR"], row["pdf_filename"]))
    assert db.execute("SELECT sent_to FROM invoice_versions").fetchone()[0] is None


def test_a_sent_invoice_can_be_emailed_again(client, db, gmail, draft):
    client.post(f"/invoices/{draft}/send", headers=FETCH)

    client.post(f"/invoices/{draft}/again")

    assert len(gmail.outbox) == 2 and gmail.outbox[1]["body_text"] == gmail.outbox[0]["body_text"]


def test_an_old_draft_from_before_terms_sends_its_own_pdf_and_total(client, db, app, gmail, make_student, make_invoice):
    old = make_invoice(make_student(email="pat@example.com"), total=280)
    path = os.path.join(app.config["INVOICE_PDF_DIR"], invoice(db, old)["pdf_filename"])
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4 test")

    result = client.post(f"/invoices/{old}/send", headers=FETCH).get_json()

    assert result["status"] == "sent"
    assert gmail.outbox[0]["pdf_fullpath"] == path and "Total: $280.00" in gmail.outbox[0]["body_text"]
    assert (invoice(db, old)["status"], invoice(db, old)["total"]) == ("sent", 280.0)


def test_an_old_draft_without_its_pdf_is_not_sent(client, db, gmail, make_student, make_invoice):
    old = make_invoice(make_student())

    result = client.post(f"/invoices/{old}/send", headers=FETCH).get_json()

    assert result["status"] == "failed" and "PDF isn’t on the server" in result["message"]
    assert gmail.outbox == [] and invoice(db, old)["status"] == "draft"


def test_the_list_page_sends_one_invoice_per_request(client, draft):
    html = page(client, "/invoices")

    assert 'id="sendModal"' in html and "/invoices/999999999/send" in html


# ---------------- Gmail sign-in ----------------

def token_file(tmp_path, **fields):
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", **fields}))
    return str(path)


def test_gmail_is_never_signed_in_during_a_web_request(app, tmp_path):
    app.config["GOOGLE_OAUTH_TOKEN"] = str(tmp_path / "missing.json")

    with app.app_context(), pytest.raises(GmailNotConnected):
        email_service.gmail_service()


def test_an_unreadable_saved_sign_in_means_not_connected(app, tmp_path):
    app.config["GOOGLE_OAUTH_TOKEN"] = str(tmp_path / "token.json")
    (tmp_path / "token.json").write_text("{not json")

    with app.app_context(), pytest.raises(GmailNotConnected, match="can't be read"):
        email_service.gmail_service()


def test_a_sign_in_google_has_cancelled_means_not_connected(app, tmp_path, monkeypatch):
    app.config["GOOGLE_OAUTH_TOKEN"] = token_file(tmp_path, refresh_token="revoked")

    def refused(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", refused)
    with app.app_context(), pytest.raises(GmailNotConnected, match="connected again"):
        email_service.gmail_service()


class FakeFlow:
    """Stands in for Google's sign-in flow."""
    def __init__(self):
        self.credentials = SimpleNamespace(to_json=lambda: '{"token": "new"}')
        self.code = None

    def authorization_url(self, **kwargs):
        return "https://accounts.google.com/o/oauth2/auth?state=abc123", "abc123"

    def fetch_token(self, code):
        self.code = code


@pytest.fixture
def sign_in(tmp_path, monkeypatch):
    (tmp_path / "credentials.json").write_text("{}")
    config = SimpleNamespace(GOOGLE_OAUTH_CREDENTIALS=str(tmp_path / "credentials.json"),
                             GOOGLE_OAUTH_TOKEN=str(tmp_path / "token.json"),
                             OAUTH_PORT=8090, SENDER_EMAIL="teacher@example.com")
    flow = FakeFlow()
    monkeypatch.setattr(gmail_auth, "get_config", lambda: config)
    monkeypatch.setattr(gmail_auth.InstalledAppFlow, "from_client_secrets_file", lambda *a, **k: flow)
    return SimpleNamespace(flow=flow, token=tmp_path / "token.json")


def test_connecting_gmail_saves_the_sign_in(sign_in, capsys):
    pasted = "http://localhost:8090/?state=abc123&code=4/0Abc&scope=https://www.googleapis.com/auth/gmail.send"

    assert gmail_auth.main(ask=lambda prompt: pasted) == 0

    assert sign_in.flow.code == "4/0Abc"
    assert sign_in.token.read_text() == '{"token": "new"}'
    assert "sign in as teacher@example.com" in capsys.readouterr().out


@pytest.mark.parametrize("pasted, message", [
    ("http://localhost:8090/?state=other&code=4/0Abc", "different attempt"),
    ("http://localhost:8090/?state=abc123&error=access_denied", "access_denied"),
    ("I clicked allow", "doesn't contain Google's answer"),
])
def test_connecting_gmail_with_the_wrong_address_changes_nothing(sign_in, capsys, pasted, message):
    assert gmail_auth.main(ask=lambda prompt: pasted) == 1

    assert message in capsys.readouterr().out
    assert not sign_in.token.exists()
