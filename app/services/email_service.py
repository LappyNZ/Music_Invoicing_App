import os
import base64
import mimetypes
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request


GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def gmail_service():
    token_path = current_app.config["GOOGLE_OAUTH_TOKEN"]
    credentials_path = current_app.config["GOOGLE_OAUTH_CREDENTIALS"]
    oauth_port = int(current_app.config["OAUTH_PORT"])

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path,
                GMAIL_SCOPES,
            )
            creds = flow.run_local_server(
                host="0.0.0.0",
                port=oauth_port,
                prompt="consent",
                open_browser=False,
            )

        with open(token_path, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def send_invoice_via_gmail(
    to_email: str,
    subject: str,
    body_text: str,
    pdf_fullpath: str,
    sender_email: str,
    sender_name: str,
):
    if not current_app.config.get("EMAIL_ENABLED", True):
        current_app.logger.warning(
            f"[DEV BLOCK] Email prevented → to={to_email}, subject={subject}"
        )
        return {"status": "blocked", "to": to_email}

    redirect_to = current_app.config.get("EMAIL_REDIRECT_TO")
    actual_to = redirect_to if redirect_to else to_email

    if redirect_to:
        current_app.logger.warning(
            f"[DEV REDIRECT] {to_email} → {actual_to}"
        )

    if not os.path.exists(pdf_fullpath):
        raise FileNotFoundError(f"Missing PDF: {pdf_fullpath}")

    msg = EmailMessage()
    msg["To"] = actual_to
    msg["From"] = formataddr((sender_name, sender_email))
    msg["Subject"] = subject
    msg["Reply-To"] = formataddr((sender_name, sender_email))
    msg.set_content(body_text)

    ctype, encoding = mimetypes.guess_type(pdf_fullpath)
    if ctype is None or encoding is not None:
        ctype = "application/pdf"
    maintype, subtype = ctype.split("/", 1)

    with open(pdf_fullpath, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype=maintype,
            subtype=subtype,
            filename=os.path.basename(pdf_fullpath),
        )

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    svc = gmail_service()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()

    return {"status": "sent", "to": actual_to}