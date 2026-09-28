import os
from io import BytesIO

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file,
                   send_from_directory, url_for)

import billing as B
import terms as T
from db import get_db
from services import invoice_service as S
from services.email_service import GmailNotConnected
from utils import fmt_dm, fmt_full, invoice_number_of, money, pdf_filename_of, to_cents

invoices_bp = Blueprint("invoices_bp", __name__)

GMAIL_HELP = "Nothing more was sent. Gmail needs connecting again (see the Unraid README), then send the rest."
LABELS = {"draft": "Draft", "revising": "Being corrected", "unpaid": "Sent, not paid", "part": "Part paid", "paid": "Paid",
          "carried": "Moved on", "written_off": "Written off", "void": "Void"}
TONES = {"draft": "", "revising": "warn", "unpaid": "accent", "part": "warn", "paid": "ok", "carried": "", "written_off": "", "void": ""}


def wants_json():
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


def load(conn, invoice_id):
    inv = B.get_invoice(conn, invoice_id)
    if not inv:
        conn.close()
        abort(404)
    return inv


def state_label(conn, inv, st):
    if st == "carried":
        target = B.get_invoice(conn, inv["carried_to"]) if inv["carried_to"] else None
        return f"Moved to {target['invoice_number']}" if target else "Moved to next invoice"
    return LABELS[st]


def summary(conn, inv):
    """What a list needs to show about one invoice."""
    st = B.state(conn, inv)
    students = B.invoice_students(conn, inv)
    total, paid = B.total_cents(conn, inv), B.paid_cents(conn, inv)
    term = T.get_term(conn, inv["term_id"]) if inv["term_id"] else None
    payer = S.payer(conn, inv)
    return {"id": inv["id"], "number": invoice_number_of(inv),
            "names": S.list_text(s["name"] for s in students) if students else f"Deleted student #{inv['student_id']}",
            "bill_to": S.bill_to(payer) if payer else "", "total": total, "paid": paid, "owing": total - paid, "state": st,
            "label": state_label(conn, inv, st), "tone": TONES[st], "extras": B.extras_cents(B.current_lines(conn, inv)),
            "term": term["name"] if term else "Before terms", "sent": (inv["emailed_at"] or "")[:10]}


def back(invoice_id, tab=None):
    return redirect(url_for("invoices_bp.invoice", invoice_id=invoice_id, tab=tab) if tab else url_for("invoices_bp.invoice", invoice_id=invoice_id))


# ---------------------------------------------------------------- the list

@invoices_bp.route("/invoices")
def invoice_list():
    conn = get_db()
    show = request.args.get("show", "term")
    terms = T.all_terms(conn)
    term = T.get_term(conn, request.args.get("term", type=int) or 0) or T.invoicing_term(conn, T.today())
    student_id = request.args.get("student_id", type=int)
    student = None
    if student_id:
        show = "student"
        student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        invoices = conn.execute("""SELECT * FROM invoices WHERE student_id=? OR id IN (SELECT invoice_id FROM lessons WHERE student_id=?)
                                   ORDER BY id DESC""", (student_id, student_id)).fetchall()
    elif show == "unpaid":
        invoices = [i for i in conn.execute("SELECT * FROM invoices ORDER BY emailed_at, id").fetchall() if B.is_open(conn, i)]
    elif show == "all":
        invoices = conn.execute("SELECT * FROM invoices ORDER BY id DESC").fetchall()
    else:
        invoices = conn.execute("SELECT * FROM invoices WHERE term_id=? ORDER BY invoice_number", (term["id"],)).fetchall() if term else []
    rows = [summary(conn, i) for i in invoices]
    unbilled = B.unbilled_students(conn, term) if term and show == "term" else []
    students = conn.execute("SELECT id, name FROM students WHERE active = 1 ORDER BY name").fetchall()
    conn.close()
    live = [r for r in rows if r["state"] != "void"]
    return render_template("invoice_list.html", rows=rows, show=show, terms=terms, term=term, unbilled=unbilled, students=students,
                           student=student, student_id=student_id,
                           drafts=[r for r in rows if r["state"] == "draft"],
                           invoiced=sum(r["total"] for r in live), paid=sum(r["paid"] for r in live),
                           owing=sum(r["owing"] for r in live if r["state"] in ("unpaid", "part")))


@invoices_bp.route("/invoices/list")
def old_list():
    return redirect(url_for("invoices_bp.invoice_list"), code=301)


@invoices_bp.route("/invoices/make", methods=["GET", "POST"])
def make_invoices():
    conn = get_db()
    term = T.get_term(conn, request.values.get("term", type=int) or 0) or T.invoicing_term(conn, T.today())
    if request.method == "POST":
        made = B.make_drafts(conn, term, family=bool(request.form.get("family")), carry=bool(request.form.get("carry")))
        conn.commit()
        conn.close()
        if made:
            flash(f"{len(made)} draft invoice{'s' if len(made) != 1 else ''} made. Nothing has been emailed yet: check them, then send.", "success")
        else:
            flash("There was nothing new to invoice.", "info")
        return redirect(url_for("invoices_bp.invoice_list", term=term["id"]))

    unbilled = B.unbilled_students(conn, term)
    ids = [s["id"] for s in unbilled]
    owing = [{"number": invoice_number_of(i), "name": S.payer(conn, i)["name"], "owing": B.owing_cents(conn, i),
              "state": B.state(conn, i)} for i in B.owing_from_before(conn, ids, term)]
    families = {}
    for s in unbilled:
        if s["email"]:
            families.setdefault(s["email"].strip().lower(), []).append(s["name"])
    today = T.today()
    checked = T.checked_weeks(conn, term)
    unchecked = [w for w in range(1, T.term_weeks(term) + 1) if w not in checked and T.week_start(term, w) <= today]
    elsewhere = [dict(r, period=f"{fmt_dm(T.day(r['start_date']))} to {fmt_full(T.day(r['end_date']))}") for r in B.already_billed_elsewhere(conn, term)]
    conn.close()
    return render_template("make_invoices.html", term=term, unbilled=unbilled, owing=owing,
                           families=[S.list_text(names) for names in families.values() if len(names) > 1], unchecked=unchecked,
                           running=T.day(term["end_date"]) >= today, elsewhere=elsewhere, owing_total=sum(o["owing"] for o in owing))


@invoices_bp.route("/invoices/make/release", methods=["POST"])
def release_lessons():
    conn = get_db()
    term = T.get_term(conn, request.form.get("term", type=int) or 0)
    old = B.get_invoice(conn, request.form.get("invoice", type=int) or 0)
    if term and old and old["term_id"] is None:
        B.release_to_term(conn, term, old["id"])
        B.log(conn, old["id"], f"Its lessons in {term['name']} will be billed on {term['name']} invoices instead")
        conn.commit()
        flash(f"Those lessons will go on the {term['name']} invoices.", "success")
    conn.close()
    return redirect(url_for("invoices_bp.make_invoices", term=request.form.get("term")))


@invoices_bp.route("/invoices/new", methods=["POST"])
def one_off():
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (request.form.get("student_id", type=int) or 0,)).fetchone()
    term = T.get_term(conn, request.form.get("term", type=int) or 0) or T.current_term(conn, T.today())
    if not student or not term:
        conn.close()
        flash("Choose a student first.", "warning")
        return redirect(url_for("invoices_bp.invoice_list"))
    inv = B.new_one_off(conn, term, student)
    conn.commit()
    conn.close()
    flash("Add what it’s for, then send it.", "info")
    return back(inv["id"])


# ---------------------------------------------------------------- one invoice

@invoices_bp.route("/invoices/<int:invoice_id>")
def invoice(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    if inv["status"] in ("draft", "revising"):
        B.attach_new_lessons(conn, inv)
        B.refresh_total(conn, inv["id"])
        conn.commit()
        inv = B.get_invoice(conn, invoice_id)
    st = B.state(conn, inv)
    lines = B.current_lines(conn, inv)
    term = T.get_term(conn, inv["term_id"]) if inv["term_id"] else None
    for line in lines:
        if term and line.get("date"):
            line["week"] = T.week_of(term, T.day(line["date"]))
    payer = S.payer(conn, inv)
    students = B.invoice_students(conn, inv)
    subject, body, own = S.email_for(conn, inv, lines) if students else ("", "", False)
    total, paid = B.total_cents(conn, inv), B.paid_cents(conn, inv)
    data = dict(
        inv=inv, number=invoice_number_of(inv), state=st, label=state_label(conn, inv, st), tone=TONES[st], lines=lines,
        term=term, payer=payer, bill_to=S.bill_to(payer) if payer else "", students=students,
        names=S.list_text(s["name"] for s in students) if students else f"Deleted student #{inv['student_id']}", period=S.period_text(conn, inv),
        particulars=S.particulars(students) if students else "", total=total, paid=paid, owing=total - paid,
        payments=conn.execute("SELECT * FROM payments WHERE invoice_id=? ORDER BY paid_on, id", (invoice_id,)).fetchall(),
        versions=conn.execute("SELECT * FROM invoice_versions WHERE invoice_id=? ORDER BY revision DESC", (invoice_id,)).fetchall(),
        events=conn.execute("SELECT * FROM invoice_events WHERE invoice_id=? ORDER BY id DESC", (invoice_id,)).fetchall(),
        changes=B.changes_since_sent(conn, inv), subject=subject, body=body, own_wording=own,
        carried_to=B.get_invoice(conn, inv["carried_to"]) if inv["carried_to"] else None,
        legacy=B.is_legacy(inv), editable=inv["status"] in ("draft", "revising"), tab=request.args.get("tab", "invoice"),
        issued=fmt_full(T.today()), today_iso=T.today().isoformat(), sender_email=current_app.config["SENDER_EMAIL"], bank=current_app.config["BANK_ACCOUNT"],
        pdf_exists=bool(inv["pdf_filename"] or B.is_legacy(inv)) and os.path.isfile(
            os.path.join(current_app.config["INVOICE_PDF_DIR"], pdf_filename_of(inv))),
    )
    conn.close()
    return render_template("invoice.html", **data)


def editable_or_back(conn, inv):
    if inv["status"] not in ("draft", "revising"):
        conn.close()
        flash("This invoice has been sent. Use “Correct and resend” to change it.", "warning")
        return back(inv["id"])
    return None


@invoices_bp.route("/invoices/<int:invoice_id>/items", methods=["POST"])
def add_item(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    stop = editable_or_back(conn, inv)
    if stop:
        return stop
    description, cents = request.form.get("description", "").strip(), to_cents(request.form.get("amount"))
    if not description or cents in (None, 0):
        flash("Type what it’s for and an amount, e.g. 120.00 (or −20 for a discount).", "warning")
    else:
        B.add_item(conn, inv, description, cents)
        conn.commit()
        flash(f"Added: {description} {money(cents)}", "success")
    conn.close()
    return back(invoice_id)


@invoices_bp.route("/invoices/<int:invoice_id>/items/<int:item_id>/delete", methods=["POST"])
def remove_item(invoice_id, item_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    stop = editable_or_back(conn, inv)
    if stop:
        return stop
    B.remove_item(conn, inv, item_id)
    conn.commit()
    conn.close()
    return back(invoice_id)


@invoices_bp.route("/invoices/<int:invoice_id>/email", methods=["POST"])
def save_email(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    if request.form.get("action") == "reset":
        conn.execute("UPDATE invoices SET email_subject=NULL, email_body=NULL WHERE id=?", (invoice_id,))
        flash("Back to the standard wording.", "success")
    else:
        subject, body = request.form.get("subject", "").strip(), request.form.get("body", "").strip()
        standard_subject, standard_body = S.default_email(conn, inv, B.current_lines(conn, inv))
        conn.execute("UPDATE invoices SET email_subject=?, email_body=? WHERE id=?",
                     (subject if subject and subject != standard_subject else None,
                      body if body and body != standard_body else None, invoice_id))
        B.log(conn, invoice_id, "Email wording changed")
        flash("Saved. This invoice’s email will use your wording.", "success")
    conn.commit()
    conn.close()
    return back(invoice_id, "email")


@invoices_bp.route("/invoices/send/<int:invoice_id>", methods=["POST"])   # the address older pages used
@invoices_bp.route("/invoices/<int:invoice_id>/send", methods=["POST"])
def send(invoice_id):
    conn = get_db()
    inv = B.get_invoice(conn, invoice_id)
    code = 200
    if not inv:
        result, code = {"status": "failed", "message": f"Invoice {invoice_id} not found."}, 404
    elif inv["status"] not in ("draft", "revising"):
        result = {"status": "skipped", "message": f"{invoice_number_of(inv)}: already sent."}
    else:
        try:
            result = S.deliver(conn, inv)
            conn.commit()
        except GmailNotConnected as e:
            result, code = {"status": "gmail_not_connected", "message": f"{e} {GMAIL_HELP}"}, 503
    conn.close()
    if wants_json():
        return jsonify(result), code
    flash(result["message"], {"sent": "success", "gmail_not_connected": "danger"}.get(result["status"], "warning"))
    return back(invoice_id) if inv else redirect(url_for("invoices_bp.invoice_list"))


@invoices_bp.route("/invoices/<int:invoice_id>/test-copy", methods=["POST"])
def test_copy(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    try:
        result = S.send_test_copy(conn, inv)
        conn.commit()
        flash(f"A copy was emailed to {result['to']}. The family hasn’t been sent anything." if result["status"] == "sent"
              else "Email is switched off here (EMAIL_ENABLED), so no copy was sent." if result["status"] == "blocked"
              else f"The copy couldn’t be sent: {result.get('message', '')}", "success" if result["status"] == "sent" else "warning")
    except GmailNotConnected as e:
        flash(f"{e} Gmail needs connecting again (see the Unraid README).", "danger")
    conn.close()
    return back(invoice_id)


@invoices_bp.route("/invoices/<int:invoice_id>/again", methods=["POST"])
def again(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    try:
        result = S.email_again(conn, inv)
        conn.commit()
        flash(f"Emailed again to {result['to']}." if result["status"] == "sent" else result.get("message") or "Email is switched off here.",
              "success" if result["status"] == "sent" else "warning")
    except GmailNotConnected as e:
        flash(f"{e} Gmail needs connecting again (see the Unraid README).", "danger")
    conn.close()
    return back(invoice_id)


@invoices_bp.route("/invoices/<int:invoice_id>/mark-sent", methods=["POST"])
def mark_sent(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    stop = editable_or_back(conn, inv)
    if stop:
        return stop
    S.mark_sent_without_email(conn, inv)
    conn.commit()
    conn.close()
    flash("Marked as sent. Nobody was emailed.", "success")
    return back(invoice_id)


@invoices_bp.route("/invoices/<int:invoice_id>/payments", methods=["POST"])
def add_payment(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    cents, paid_on = to_cents(request.form.get("amount")), request.form.get("paid_on", "")
    if cents is None or cents <= 0:
        flash("Type the amount received, e.g. 300.00. Nothing was saved.", "warning")
    elif not T.valid_date(paid_on):
        flash("The date wasn’t understood. Nothing was saved.", "warning")
    else:
        B.add_payment(conn, inv, cents, paid_on, request.form.get("reference", "").strip())
        conn.commit()
        owing = B.owing_cents(conn, B.get_invoice(conn, invoice_id))
        flash(f"Payment saved. {money(owing)} still to pay." if owing > 0 else "Payment saved. It’s paid in full.", "success")
    conn.close()
    return back(invoice_id)


@invoices_bp.route("/invoices/<int:invoice_id>/payments/<int:payment_id>/delete", methods=["POST"])
def delete_payment(invoice_id, payment_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    B.delete_payment(conn, inv, payment_id)
    conn.commit()
    conn.close()
    flash("Payment removed.", "success")
    return back(invoice_id)


def close_action(invoice_id, fn, message, allowed=("unpaid", "part")):
    conn = get_db()
    inv = load(conn, invoice_id)
    if B.state(conn, inv) not in allowed:
        flash("That can’t be done to this invoice now.", "warning")
    else:
        said = fn(conn, inv)
        conn.commit()
        flash(said if isinstance(said, str) else message, "success")
    conn.close()
    return back(invoice_id)


@invoices_bp.route("/invoices/<int:invoice_id>/move", methods=["POST"])
def move_to_next(invoice_id):
    def move(conn, inv):
        draft = B.move_to_next(conn, inv)
        return f"The amount still owing is now on draft {draft['invoice_number']}." if draft else None
    return close_action(invoice_id, move, "The amount still owing will go on this family’s next invoice.")


@invoices_bp.route("/invoices/<int:invoice_id>/write-off", methods=["POST"])
def write_off(invoice_id):
    reason = request.form.get("reason", "").strip()
    return close_action(invoice_id, lambda conn, inv: B.write_off(conn, inv, reason), "Written off. It stays in your records.")


@invoices_bp.route("/invoices/<int:invoice_id>/void", methods=["POST"])
def void(invoice_id):
    reason = request.form.get("reason", "").strip()
    return close_action(invoice_id, lambda conn, inv: B.void(conn, inv, reason),
                        "Voided. Its lessons can go on a new invoice.", allowed=("unpaid", "paid", "part"))


@invoices_bp.route("/invoices/<int:invoice_id>/undo", methods=["POST"])
def undo(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    problem = B.undo_close(conn, inv) if inv["status"] in B.CLOSED else "There’s nothing to undo."
    if problem:
        conn.rollback()
        flash(problem, "warning")
    else:
        conn.commit()
        flash("Undone.", "success")
    conn.close()
    return back(invoice_id)


@invoices_bp.route("/invoices/<int:invoice_id>/correct", methods=["POST"])
def correct(invoice_id):
    return close_action(invoice_id, B.start_correction, "Change the register or the items, then resend it.",
                        allowed=("unpaid", "part", "paid"))


@invoices_bp.route("/invoices/<int:invoice_id>/correct/cancel", methods=["POST"])
def cancel_correction(invoice_id):
    return close_action(invoice_id, B.cancel_correction, "Correction cancelled. It’s back as it was sent.", allowed=("revising",))


@invoices_bp.route("/invoices/<int:invoice_id>/delete", methods=["POST"])
def delete_draft(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    if inv["status"] != "draft":
        conn.close()
        flash("Only drafts can be deleted. Void a sent invoice instead.", "warning")
        return back(invoice_id)
    term_id = inv["term_id"]
    B.delete_draft(conn, inv)
    conn.commit()
    conn.close()
    flash(f"Draft {invoice_number_of(inv)} deleted. Its lessons will go on the next invoices you make.", "success")
    return redirect(url_for("invoices_bp.invoice_list", term=term_id))


@invoices_bp.route("/invoices/pdf/<int:invoice_id>")
@invoices_bp.route("/invoices/<int:invoice_id>/pdf")
def pdf(invoice_id):
    conn = get_db()
    inv = load(conn, invoice_id)
    if inv["status"] in ("draft", "revising") and not B.is_legacy(inv):
        buffer = BytesIO()
        B.attach_new_lessons(conn, inv)
        S.write_pdf(conn, inv, buffer, B.live_lines(conn, inv))
        conn.commit()
        conn.close()
        buffer.seek(0)
        return send_file(buffer, mimetype="application/pdf", download_name=f"{invoice_number_of(inv)}-draft.pdf")
    conn.close()
    filename = pdf_filename_of(inv)
    if not os.path.isfile(os.path.join(current_app.config["INVOICE_PDF_DIR"], filename)):
        flash("That PDF isn’t on the server.", "warning")
        return back(invoice_id)
    return send_from_directory(current_app.config["INVOICE_PDF_DIR"], filename, mimetype="application/pdf")
