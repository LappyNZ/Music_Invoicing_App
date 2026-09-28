"""Turning an invoice into its PDF and email, and sending it."""
import os

from flask import current_app

import billing as B
import terms as T
from services.email_service import GmailNotConnected, send_invoice_via_gmail
from services.pdf_service import build_invoice_pdf
from utils import fmt_dm, fmt_full, invoice_number_of, money, pdf_filename_of


def list_text(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def bill_to(student):
    return (student["parent"] or "").strip() or student["name"]


def particulars(students):
    """What payers put in the bank's Particulars field: the student, or the family."""
    if len(students) == 1:
        return students[0]["name"]
    surnames = {s["name"].split()[-1] for s in students}
    return f"{surnames.pop()} family" if len(surnames) == 1 else " & ".join(s["name"].split()[0] for s in students)


def payer(conn, inv):
    return conn.execute("SELECT * FROM students WHERE id=?", (inv["student_id"],)).fetchone()


def period_text(conn, inv):
    if inv["term_id"]:
        term = T.get_term(conn, inv["term_id"])
        return f"{term['name']}, {fmt_dm(T.day(term['start_date']))} to {fmt_dm(T.day(term['end_date']))}"
    if inv["start_date"] and inv["end_date"]:
        return f"{fmt_dm(T.day(inv['start_date']))} to {fmt_dm(T.day(inv['end_date']))}"
    return ""


def default_email(conn, inv, lines):
    cfg = current_app.config
    students = B.invoice_students(conn, inv)
    student = payer(conn, inv) or students[0]
    number = invoice_number_of(inv)
    term = T.get_term(conn, inv["term_id"]) if inv["term_id"] else None
    term_name = term["name"] if term else ""
    short = term_name.rsplit(" ", 1)[0] if term_name[-4:].isdigit() else term_name
    if term:
        when = f"{short} ({fmt_dm(T.day(term['start_date']))} to {fmt_dm(T.day(term['end_date']))})"
    else:   # made before terms: only its dates are known
        when = f"the period {period_text(conn, inv)}" if inv["start_date"] and inv["end_date"] else "the last few weeks"
    who = list_text(s["name"] for s in students)
    names = list_text(s["name"].split()[0] for s in students)
    self_pay = len(students) == 1 and not (student["parent"] or "").strip()
    has_lessons = B.is_legacy(inv) or any(line["kind"] in ("lesson", "extra", "missed", "cancelled") for line in lines)
    carried = sum(line["cents"] for line in lines if line["kind"] == "carried")
    total = B.total_cents(conn, inv) if B.is_legacy(inv) else sum(line["cents"] for line in lines)
    revised = inv["revision"] > 1

    subject = f"{'Corrected: ' if revised else ''}Cello lessons{', ' + term_name if term_name else ''} – {who} ({number})"
    body = [f"Kia ora {bill_to(student).split()[0]},", ""]
    if revised:
        body.append("This corrected invoice replaces the one I sent earlier.")
    if not has_lessons:
        body.append(f"Here is an invoice for {'you' if self_pay else who}.")
    elif self_pay:
        body.append(f"Here is your invoice for cello lessons in {when}.")
    else:
        body.append(f"Here is the invoice for {names}’s cello lessons in {when}.")
    if carried:
        body.append(f"It includes {money(carried)} still owing from an earlier invoice.")
    body += ["", f"Total: {money(total)}. Prompt payment is appreciated.", "",
             "Payment details:", f"Bank account: {cfg['BANK_ACCOUNT']}", f"Reference: {number}",
             f"Particulars: {particulars(students)}", "", "Ngā mihi,", cfg["SENDER_NAME"]]
    return subject, "\n".join(body)


def email_for(conn, inv, lines):
    """(subject, body, uses_own_wording) for this invoice's email."""
    subject, body = default_email(conn, inv, lines)
    own = bool(inv["email_subject"] or inv["email_body"])
    return inv["email_subject"] or subject, inv["email_body"] or body, own


def pdf_filename(inv):
    number = invoice_number_of(inv)
    return f"{number}.pdf" if inv["revision"] == 1 else f"{number}-v{inv['revision']}.pdf"


def write_pdf(conn, inv, target, lines, issued=None):
    cfg = current_app.config
    students = B.invoice_students(conn, inv)
    student = payer(conn, inv) or students[0]
    note = ""
    if inv["revision"] > 1:
        previous = conn.execute("SELECT sent_at FROM invoice_versions WHERE invoice_id=? AND revision<? ORDER BY revision DESC LIMIT 1",
                                (inv["id"], inv["revision"])).fetchone()
        when = f" on {fmt_full(T.day(previous['sent_at']))}" if previous else ""
        note = f"Corrected invoice (version {inv['revision']}). It replaces the one sent{when}."
    build_invoice_pdf(
        target,
        logo_path=os.path.join(current_app.root_path, cfg["STATIC_DIR"], cfg["LOGO_FILE"]),
        business={"name": cfg["BUSINESS_NAME"], "address1": cfg["BUSINESS_ADDRESS_LINE1"], "address2": cfg["BUSINESS_ADDRESS_LINE2"],
                  "phone": cfg["BUSINESS_PHONE"], "mobile": cfg["BUSINESS_MOBILE"], "email": cfg["SENDER_EMAIL"],
                  "bank": cfg["BANK_ACCOUNT"]},
        number=invoice_number_of(inv), issued=issued or fmt_full(T.today()), bill_to=bill_to(student), bill_to_email=student["email"],
        for_names=list_text(s["name"] for s in students), period=period_text(conn, inv), lines=lines,
        total_cents=sum(line["cents"] for line in lines), particulars=particulars(students), revised_note=note)


def _send(to, subject, body, path):
    cfg = current_app.config
    return send_invoice_via_gmail(to_email=to, subject=subject, body_text=body, pdf_fullpath=path,
                                  sender_email=cfg["SENDER_EMAIL"], sender_name=cfg["SENDER_NAME"])


def old_pdf_path(inv):
    """The PDF of an invoice made before terms: the old app wrote it when the invoice was made."""
    return os.path.join(current_app.config["INVOICE_PDF_DIR"], pdf_filename_of(inv))


def deliver(conn, inv):
    """Email a draft (or a correction) with its PDF and record it as sent.

    Returns {"status": sent | blocked | skipped | failed, "message": ...}. Raises GmailNotConnected, which should
    stop any further sending.
    """
    number = invoice_number_of(inv)
    student = payer(conn, inv)
    to = ((student["email"] if student else "") or "").strip()
    if not to:
        return {"status": "skipped", "message": f"{number}: {student['name'] if student else 'the student'} has no email address."}
    legacy = B.is_legacy(inv)
    if legacy:
        lines, filename, path = [], pdf_filename_of(inv), old_pdf_path(inv)
        if not os.path.isfile(path):
            return {"status": "failed", "message": f"{number}: its PDF isn’t on the server. Delete this old draft and make the invoice again."}
    else:
        B.attach_new_lessons(conn, inv)
        lines = B.live_lines(conn, inv)
        filename = pdf_filename(inv)
        path = os.path.join(current_app.config["INVOICE_PDF_DIR"], filename)
    subject, body, _ = email_for(conn, inv, lines)
    try:
        if not legacy:
            write_pdf(conn, inv, path, lines)
        result = _send(to, subject, body, path)
    except GmailNotConnected:
        raise
    except Exception as e:  # a bad address, Google refusing, a full disk: this invoice fails, the rest can go
        return {"status": "failed", "message": f"{number}: {e}"}
    if result["status"] == "sent":
        B.record_sent(conn, inv, result["to"], filename, subject, body)
        return {"status": "sent", "message": f"{number}: emailed to {result['to']}."}
    if result["status"] == "blocked":
        return {"status": "blocked", "message": f"{number}: email is switched off here (EMAIL_ENABLED)."}
    return {"status": "failed", "message": f"{number}: {result.get('message', 'not sent')}"}


def send_test_copy(conn, inv):
    """Email the invoice to the studio's own address, exactly as the family would get it, without sending it."""
    number = invoice_number_of(inv)
    legacy = B.is_legacy(inv)
    lines = [] if legacy else B.current_lines(conn, inv)
    subject, body, _ = email_for(conn, inv, lines)
    path = old_pdf_path(inv) if legacy else os.path.join(current_app.config["INVOICE_PDF_DIR"], f"{number}-test-copy.pdf")
    if legacy and not os.path.isfile(path):
        return {"status": "failed", "message": "its PDF isn’t on the server."}
    try:
        if not legacy:
            write_pdf(conn, inv, path, lines)
        result = _send(current_app.config["SENDER_EMAIL"], f"[Test copy] {subject}", body, path)
    except GmailNotConnected:
        raise
    except Exception as e:
        return {"status": "failed", "message": str(e)}
    finally:
        if not legacy and os.path.exists(path):
            os.remove(path)
    if result["status"] == "sent":
        B.log(conn, inv["id"], f"Test copy emailed to {result['to']}")
    return result


def email_again(conn, inv):
    """Send the invoice as last sent to the family again (e.g. they can't find it)."""
    version = B.latest_version(conn, inv)
    student = payer(conn, inv)
    path = os.path.join(current_app.config["INVOICE_PDF_DIR"], (version and version["pdf_filename"]) or inv["pdf_filename"] or "")
    if not version or not os.path.isfile(path):
        return {"status": "failed", "message": "Its PDF isn’t on the server, so it can’t be emailed again."}
    result = _send(student["email"], version["email_subject"], version["email_body"], path)
    if result["status"] == "sent":
        B.log(conn, inv["id"], f"Emailed again to {result['to']}")
    return result


def mark_sent_without_email(conn, inv):
    """For an invoice handed over some other way: keep it as sent, with its PDF, but email nobody."""
    if B.is_legacy(inv):
        lines, filename = [], pdf_filename_of(inv)
    else:
        B.attach_new_lessons(conn, inv)
        lines = B.live_lines(conn, inv)
        filename = pdf_filename(inv)
        write_pdf(conn, inv, os.path.join(current_app.config["INVOICE_PDF_DIR"], filename), lines)
    subject, body, _ = email_for(conn, inv, lines)
    B.record_sent(conn, inv, None, filename, subject, body)
