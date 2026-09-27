from flask import current_app
from utils import invoice_number_of, nz_school_term
from services.email_service import GmailNotConnected, send_invoice_via_gmail

def send_invoice(inv, pdf_path, fmt_date, parse_date_any):
    has_parent = bool(inv["parent_name"])

    if has_parent:
        greeting_name = inv["parent_name"]
        body_lede = f"Please find attached the invoice for {inv['student_name']} for the period"
        to_email = inv["student_email"]
    else:
        greeting_name = inv["student_name"]
        body_lede = "Please find attached your invoice for the period"
        to_email = inv["student_email"]

    if not to_email:
        return {"status": "skipped", "message": "No email address"}

    term_label = nz_school_term(parse_date_any(inv["start_date"]))

    subject = f"Cello Lessons for {term_label} – {inv['student_name']}"

    body = (
        f"Kia ora {greeting_name},\n\n"
        f"{body_lede} {fmt_date(inv['start_date'])} to {fmt_date(inv['end_date'])}.\n\n"
        f"Total due: ${inv['total']:.2f}\n\n"
        f"Payment details:\n"
        f"Bank: {current_app.config['BANK_ACCOUNT']}\n"
        f"Reference: {invoice_number_of(inv)}\n"
        f"Particulars: {inv['student_name']}\n\n"
        f"Ngā mihi,\n"
        f"{current_app.config['SENDER_NAME']}"
    )

    try:
        result = send_invoice_via_gmail(
            to_email=to_email,
            subject=subject,
            body_text=body,
            pdf_fullpath=pdf_path,
            sender_email=current_app.config["SENDER_EMAIL"],
            sender_name=current_app.config["SENDER_NAME"],
        )
        return result
    except GmailNotConnected:
        raise  # stops the whole batch: every other invoice would fail the same way
    except Exception as e:
        return {"status": "failed", "message": str(e)}
