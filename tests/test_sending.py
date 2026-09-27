import json
import os
from types import SimpleNamespace

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

import gmail_auth
from services import email_service, invoice_service
from services.email_service import GmailNotConnected
from utils import invoice_number_of, pdf_filename_of


@pytest.fixture
def gmail(app, monkeypatch):
    """Stands in for Gmail: records what would be sent, or fails the way it's told to."""
    outbox, problem = [], {}

    def fake_send(**message):
        if "error" in problem:
            raise problem["error"]
        outbox.append(message)
        return {"status": "sent", "to": message["to_email"]}

    monkeypatch.setattr(invoice_service, "send_invoice_via_gmail", fake_send)
    return SimpleNamespace(outbox=outbox, fail_with=lambda e: problem.update(error=e))


@pytest.fixture
def pdf_for(app, db):
    """Gives an invoice the PDF file it would have had."""
    def _make(invoice_id):
        inv = db.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        with open(os.path.join(app.config["INVOICE_PDF_DIR"], pdf_filename_of(inv)), "wb") as f:
            f.write(b"%PDF-1.4 test")
        return invoice_id
    return _make


def status_of(db, invoice_id):
    return db.execute("SELECT status, emailed_to FROM invoices WHERE id=?", (invoice_id,)).fetchone()


def test_sending_one_invoice_emails_it_and_marks_it_sent(client, db, gmail, make_student, make_invoice, pdf_for):
    invoice = pdf_for(make_invoice(make_student(email="pat@example.com")))

    result = client.post(f"/invoices/send/{invoice}").get_json()

    number = invoice_number_of(db.execute("SELECT * FROM invoices WHERE id=?", (invoice,)).fetchone())
    assert result == {"status": "sent", "message": f"{number}: emailed to pat@example.com."}
    assert [m["to_email"] for m in gmail.outbox] == ["pat@example.com"]
    assert tuple(status_of(db, invoice)) == ("sent", "pat@example.com")


@pytest.mark.parametrize("status", ["paid", "void"])
def test_paid_and_void_invoices_are_not_sent(client, db, gmail, make_student, make_invoice, pdf_for, status):
    invoice = pdf_for(make_invoice(make_student(), status=status))

    result = client.post(f"/invoices/send/{invoice}").get_json()

    assert result["status"] == "skipped" and gmail.outbox == []
    assert status_of(db, invoice)[0] == status


def test_sending_stops_when_gmail_is_not_connected(client, db, gmail, make_student, make_invoice, pdf_for):
    invoice = pdf_for(make_invoice(make_student()))
    gmail.fail_with(GmailNotConnected("Gmail isn't connected to the app."))

    response = client.post(f"/invoices/send/{invoice}")

    assert response.status_code == 503
    assert response.get_json()["status"] == "gmail_not_connected"
    assert "Gmail needs connecting again" in response.get_json()["message"]
    assert status_of(db, invoice)[0] == "draft"


def test_the_all_at_once_fallback_also_stops_when_gmail_is_not_connected(client, db, gmail, make_student,
                                                                         make_invoice, pdf_for, monkeypatch):
    invoices = [pdf_for(make_invoice(make_student(f"Student {n}"))) for n in range(3)]
    attempts = []

    def not_connected(**message):
        attempts.append(message)
        raise GmailNotConnected("Gmail isn't connected to the app.")

    monkeypatch.setattr(invoice_service, "send_invoice_via_gmail", not_connected)
    page = client.post("/invoices/list", data={"action": "send", "confirm_send": "1",
                                               "invoice_id": [str(i) for i in invoices]}, follow_redirects=True)

    assert len(attempts) == 1
    assert "Stopped: Gmail isn" in page.get_data(as_text=True)
    assert [status_of(db, i)[0] for i in invoices] == ["draft"] * 3


def test_email_switched_off_is_reported(client, make_student, make_invoice, pdf_for):
    invoice = pdf_for(make_invoice(make_student()))  # the tests run with EMAIL_ENABLED=0

    result = client.post(f"/invoices/send/{invoice}").get_json()

    assert result["status"] == "blocked" and "switched off" in result["message"]


def test_the_list_page_sends_one_invoice_per_request(client, make_student, make_invoice):
    make_invoice(make_student())

    page = client.get("/invoices/list").get_data(as_text=True)

    assert 'id="sendProgressModal"' in page
    assert "/invoices/send/0" in page


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
