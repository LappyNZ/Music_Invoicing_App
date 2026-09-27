import math
import os
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_from_directory

from db import get_db
from services.email_service import GmailNotConnected
from services.invoice_service import send_invoice
from services.pdf_service import build_invoice_pdf  # only if already needed here
from utils import (DATETIME_FORMAT, fmt_date, invoice_number_of, new_invoice_number, parse_date_any,
                   parse_datetime, pdf_filename_of)

invoices_bp = Blueprint("invoices_bp", __name__)


def to_number(text):
    """The number in a form field, or None if there isn't one (including "nan" and "inf")."""
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# ---------------- Create Invoice ----------------
@invoices_bp.route("/invoices", methods=["GET", "POST"])
def invoices():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, name, parent, email FROM students WHERE active = 1 ORDER BY name")
    students = cur.fetchall()

    lessons, extras = [], []
    total = 0.0
    selected_student = start_date = end_date = None
    previewed = False

    if request.method == "POST":
        action = request.form.get("action")
        selected_student = request.form["student_id"]
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        if start_date > end_date:  # both YYYY-MM-DD
            flash("The start date is after the end date. Please check the dates.", "warning")
            conn.close()
            return render_template("invoices.html", students=students, lessons=[], extras=[], total=0.0,
                                   selected_student=selected_student, start_date=start_date,
                                   end_date=end_date, previewed=False)
        previewed = True
        problems = []  # rows that can't be read: shown for fixing, and nothing is generated

        # Posted rows were loaded for one student and period. If either has changed since,
        # they (and any extras typed with them) belong to someone else, so start again.
        loaded_for = (request.form.get("previewed_student_id"),
                      request.form.get("previewed_start_date"),
                      request.form.get("previewed_end_date"))
        has_rows = loaded_for[0] is not None
        selection_changed = has_rows and loaded_for != (selected_student, start_date, end_date)

        # Prefer posted edited rows if present
        if has_rows and not selection_changed:
            lesson_count = int(request.form.get("lesson_count", "0") or 0)
            for i in range(1, lesson_count + 1):
                date_str = (request.form.get(f"lesson_date_{i}") or "").strip()
                duration = (request.form.get(f"lesson_duration_{i}") or "").strip()
                rate     = (request.form.get(f"lesson_rate_{i}") or "").strip()
                if not (date_str or duration or rate):
                    continue
                if not date_str or to_number(duration) is None or to_number(rate) is None:
                    problems.append(f"lesson {i} needs a date, and numbers for duration and rate")
                    lessons.append({"date_str": date_str, "duration": duration, "rate": rate,
                                    "subtotal": 0.0, "problem": True})
                    continue
                duration_i = int(to_number(duration))
                rate_f = to_number(rate)
                subtotal = round((duration_i / 60.0) * rate_f, 2)
                lessons.append({
                    "date_str": date_str,
                    "duration": duration_i,
                    "rate": rate_f,
                    "subtotal": subtotal,
                })
                total += subtotal
        else:
            # First preview: fetch from DB
            cur.execute("""
                SELECT lesson_time, duration, rate
                FROM lessons
                WHERE student_id = ?
                  AND date(lesson_time) BETWEEN date(?) AND date(?)
                ORDER BY lesson_time
            """, (selected_student, start_date, end_date))
            rows = cur.fetchall()
            for r in rows:
                dt = parse_date_any(r["lesson_time"])
                try:
                    date_str = dt.strftime("%a, %-d %b %y, %-I:%M%p")
                except ValueError:
                    date_str = dt.strftime("%a, %d %b %y, %I:%M%p")
                subtotal = round((r["duration"] / 60.0) * r["rate"], 2)
                lessons.append({
                    "date_str": date_str,
                    "duration": r["duration"],
                    "rate": r["rate"],
                    "subtotal": subtotal,
                })
                total += subtotal
            if not lessons:
                flash("No lessons found for this student between those dates.", "warning")

        # Extras (posted only)
        extra_count = 0 if selection_changed else int(request.form.get("extra_count", "0") or 0)
        for i in range(1, extra_count + 1):
            desc = (request.form.get(f"extra_desc_{i}") or "").strip()
            price = (request.form.get(f"extra_price_{i}") or "").strip()
            if not (desc or price):
                continue
            if not desc or to_number(price) is None:
                problems.append(f"extra item {i} needs a description and a price")
                extras.append({"desc": desc, "price": price, "problem": True})
                continue
            extras.append({"desc": desc, "price": to_number(price)})
            total += to_number(price)

        if problems and not selection_changed:
            flash(("Not generated: " if action == "generate_pdf" else "Please fix: ")
                  + "; ".join(problems) + ".", "warning")

        if selection_changed:
            if action == "generate_pdf":
                flash("Not generated: the student or dates changed after the preview. "
                      "The lessons below have been reloaded; check them, then click Generate PDF again.", "warning")
            else:
                flash("Lessons reloaded for the new student or dates. "
                      "Edits and extra items from the previous preview were cleared.", "info")
        elif action == "generate_pdf" and not problems:
            if not lessons and not extras:
                flash("There's nothing to invoice: no lessons or extra items.", "warning")
            else:
                conn.close()
                return generate_invoice_pdf(selected_student, start_date, end_date, lessons, extras, total)

    conn.close()
    return render_template("invoices.html",
                           students=students,
                           lessons=lessons,
                           extras=extras,
                           total=total,
                           selected_student=selected_student,
                           start_date=start_date,
                           end_date=end_date,
                           previewed=previewed)

# Invoices with their student's details. LEFT JOIN, so invoices of a deleted student still show.
INVOICE_QUERY = """
    SELECT invoices.id, invoices.start_date, invoices.end_date,
           invoices.total, invoices.created_at,
           invoices.emailed_at, invoices.emailed_to,
           invoices.status, invoices.paid_at, invoices.paid_amount, invoices.paid_ref,
           invoices.voided_at, invoices.void_reason,
           invoices.invoice_number, invoices.pdf_filename,
           invoices.student_id AS student_id,
           COALESCE(students.name, 'Deleted student #' || invoices.student_id) AS student_name,
           students.parent AS parent_name,
           students.email AS student_email
    FROM invoices
    LEFT JOIN students ON invoices.student_id = students.id
"""

# ---------------- Back to the invoice list, keeping its filters ----------------
def redirect_to_list(form):
    qs = {}
    for field, param in (("return_student_id", "student_id"), ("return_start_date", "start_date"),
                         ("return_end_date", "end_date"), ("return_status", "status"),
                         ("return_term", "term"), ("return_year", "year")):
        if form.get(field):
            qs[param] = form[field]
    return redirect(url_for("invoices_bp.invoice_list", **qs))

# ---------------- Update Invoice Status ----------------
@invoices_bp.route("/invoices/status/<int:invoice_id>", methods=["POST"])
def update_invoice_status(invoice_id):
    new_status = request.form.get("status", "").strip().lower()  # 'sent' or 'paid' or 'draft'
    paid_at    = request.form.get("paid_at", "").strip()
    paid_amt   = request.form.get("paid_amount", "").strip()
    paid_ref   = request.form.get("paid_ref", "").strip()

    if new_status not in {"sent", "paid", "draft"}:
        flash("Invalid status.", "warning")
        return redirect(url_for("invoices_bp.invoice_list"))

    amount = to_number(paid_amt) if paid_amt else None
    if paid_amt and amount is None:
        flash("The amount must be a number, e.g. 45.00. Nothing was changed.", "warning")
        return redirect_to_list(request.form)
    paid_when = parse_datetime(paid_at) if paid_at else datetime.now()  # blank means now
    if paid_when is None:
        flash("The payment date wasn't understood. Nothing was changed.", "warning")
        return redirect_to_list(request.form)

    conn = get_db()
    cur = conn.cursor()

    current = cur.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not current:
        conn.close()
        flash("Invoice not found.", "danger")
        return redirect_to_list(request.form)
    if current["status"] == "void":
        conn.close()
        flash(f"Invoice {invoice_number_of(current)} is void. Restore it before changing its status.", "warning")
        return redirect_to_list(request.form)

    if new_status == "paid":
        cur.execute("""
            UPDATE invoices
               SET status='paid',
                   paid_at = ?,
                   paid_amount = COALESCE(?, paid_amount),
                   paid_ref = COALESCE(?, paid_ref)
             WHERE id=?
        """, (paid_when.strftime(DATETIME_FORMAT), amount, paid_ref or None, invoice_id))
    else:
        cur.execute("UPDATE invoices SET status=? WHERE id=?",
                    (new_status, invoice_id))

    conn.commit()
    conn.close()

    flash(f"Invoice {invoice_number_of(current)} marked as {new_status}.", "success")
    return redirect_to_list(request.form)

# ---------------- Void / Restore Invoice ----------------
# A void invoice stays in the list for the record, but can't be emailed or marked paid.
@invoices_bp.route("/invoices/void/<int:invoice_id>", methods=["POST"])
def void_invoice(invoice_id):
    reason = request.form.get("void_reason", "").strip()
    conn = get_db()
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        flash("Invoice not found.", "danger")
    elif inv["status"] == "paid":
        flash("Paid invoices can't be voided.", "warning")
    else:
        conn.execute("UPDATE invoices SET status='void', voided_at=?, void_reason=? WHERE id=?",
                     (datetime.now().isoformat(sep=' ', timespec='seconds'), reason or None, invoice_id))
        conn.commit()
        flash(f"Invoice {invoice_number_of(inv)} voided.", "success")
    conn.close()
    return redirect_to_list(request.form)


@invoices_bp.route("/invoices/restore/<int:invoice_id>", methods=["POST"])
def restore_invoice(invoice_id):
    conn = get_db()
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND status='void'", (invoice_id,)).fetchone()
    if inv:
        conn.execute("""UPDATE invoices
                           SET status = CASE WHEN emailed_at IS NULL THEN 'draft' ELSE 'sent' END,
                               voided_at = NULL, void_reason = NULL
                         WHERE id=?""", (invoice_id,))
        conn.commit()
        flash(f"Invoice {invoice_number_of(inv)} restored.", "success")
    conn.close()
    return redirect_to_list(request.form)

# Undo "Mark paid", e.g. when a payment was recorded against the wrong invoice.
@invoices_bp.route("/invoices/unpaid/<int:invoice_id>", methods=["POST"])
def mark_unpaid(invoice_id):
    conn = get_db()
    inv = conn.execute("SELECT * FROM invoices WHERE id=? AND status='paid'", (invoice_id,)).fetchone()
    if inv:
        conn.execute("""UPDATE invoices
                           SET status = CASE WHEN emailed_at IS NULL THEN 'draft' ELSE 'sent' END,
                               paid_at = NULL, paid_amount = NULL, paid_ref = NULL
                         WHERE id=?""", (invoice_id,))
        conn.commit()
        removed = " ".join(part for part in (
            f"${inv['paid_amount']:.2f}" if inv["paid_amount"] is not None else "",
            f"on {inv['paid_at']}" if inv["paid_at"] else "",
            f"(ref {inv['paid_ref']})" if inv["paid_ref"] else "") if part)
        flash(f"Invoice {invoice_number_of(inv)} is no longer marked paid."
              + (f" The payment removed was {removed}." if removed else ""), "success")
    conn.close()
    return redirect_to_list(request.form)

# ---------------- Invoice List ----------------
@invoices_bp.route("/invoices/list", methods=["GET", "POST"])
def invoice_list():
    conn = get_db()
    cur = conn.cursor()

    # Student list for filter dropdown, including archived students
    cur.execute("SELECT id, name, active FROM students ORDER BY name")
    student_options = cur.fetchall()

    # Filters
    student_id = request.args.get("student_id")
    start_date = request.args.get("start_date")
    end_date   = request.args.get("end_date")
    status     = request.args.get("status", "")
    term_filter = request.args.get("term", "")   # 'T1'/'T2'/'T3'/'T4' or ''
    year        = request.args.get("year", "")   # '2025', etc., or ''

    query = INVOICE_QUERY + " WHERE 1=1"
    params = []

    if student_id:
        query += " AND invoices.student_id = ?"
        params.append(student_id)

    if start_date:
        query += " AND date(COALESCE(invoices.start_date, date(invoices.created_at))) >= date(?)"
        params.append(start_date)

    if end_date:
        query += " AND date(COALESCE(invoices.end_date, date(invoices.created_at))) <= date(?)"
        params.append(end_date)

    if status:
        # support legacy 'unsent' as 'draft'
        if status == "unsent":
            status = "draft"
        query += " AND COALESCE(invoices.status, CASE WHEN invoices.emailed_at IS NULL THEN 'draft' ELSE 'sent' END) = ?"
        params.append(status)

    # ---- Term filter (month groups by start_date; fallback to created_at) ----
    term_to_months = {
        "T1": ("01","02","03"),
        "T2": ("04","05","06"),
        "T3": ("07","08","09"),
        "T4": ("10","11","12"),
    }
    if term_filter in term_to_months:
        m1, m2, m3 = term_filter and term_to_months[term_filter]
        query += """
          AND strftime('%m', COALESCE(invoices.start_date, date(invoices.created_at))) IN (?,?,?)
        """
        params.extend((m1, m2, m3))

    # ---- Year filter (by start_date year; fallback to created_at year) ----
    if year:
        query += " AND strftime('%Y', COALESCE(invoices.start_date, invoices.created_at)) = ?"
        params.append(year)

    query += " ORDER BY invoices.created_at DESC"
    cur.execute(query, params)
    invoices = [dict(row) for row in cur.fetchall()]

    # Build Year options dynamically from existing data (distinct years)
    cur.execute("""
      SELECT DISTINCT strftime('%Y', COALESCE(start_date, created_at)) AS yr
      FROM invoices
      WHERE yr IS NOT NULL
      ORDER BY yr DESC
    """.replace("yr","yr"))
    year_options = [r[0] for r in cur.fetchall() if r[0]]

    # ---------------- Handle sending emails ----------------
    if request.method == "POST" \
        and request.form.get("action") == "send" \
        and request.form.get("confirm_send") == "1":
        
        selected_ids = request.form.getlist("invoice_id")
        if not selected_ids:
            flash("No invoices selected to email.", "warning")
            conn.close()
            return redirect(url_for("invoices_bp.invoice_list",
                                    student_id=student_id,
                                    start_date=start_date,
                                    end_date=end_date,
                                    status=status,
                                    term=term_filter,
                                    year=year))

        sent, skipped, failed = 0, 0, 0
        errors = []

        for sid in selected_ids:
            inv = next((i for i in invoices if str(i["id"]) == sid), None)
            if not inv:
                failed += 1
                errors.append(f"Invoice {sid}: not found in filter.")
                continue

            try:
                result = email_invoice(inv)
            except GmailNotConnected as e:
                errors.insert(0, f"Stopped: {e} {GMAIL_HELP}")
                failed += 1
                break

            if result["status"] == "sent":
                sent += 1
            elif result["status"] in ("blocked", "skipped"):
                skipped += 1
                errors.append(result["message"])
            else:
                failed += 1
                errors.append(result["message"])

        summary = f"Emailed: {sent}, Not sent: {skipped}, Failed: {failed}"
        flash(summary, "success" if failed == 0 else "warning")
        if errors:
            flash(" • ".join(errors[:5]) + (" ..." if len(errors) > 5 else ""), "secondary")

        conn.close()
        return redirect(url_for("invoices_bp.invoice_list",
                                student_id=student_id,
                                start_date=start_date,
                                end_date=end_date,
                                status=status,
                                term=term_filter,
                                year=year))

    # Render page
    conn.close()
    return render_template(
        "invoice_list.html",
        invoices=invoices,
        student_options=student_options,
        selected_student=student_id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        term=term_filter,
        year=year,
        year_options=year_options,
    )

# ---------------- Email one invoice ----------------
GMAIL_HELP = "Nothing more was sent. Gmail needs connecting again (see the Unraid README), then send the rest."


def email_invoice(inv):
    """Email one invoice (a row from INVOICE_QUERY) and record that it was sent.
    Raises GmailNotConnected, which should stop any further sending."""
    number = invoice_number_of(inv)
    st = inv["status"] or ("sent" if inv["emailed_at"] else "draft")
    if st in ("paid", "void"):
        return {"status": "skipped", "message": f"{number}: {st}, so not emailed."}

    pdf_path = os.path.join(current_app.config["INVOICE_PDF_DIR"], pdf_filename_of(inv))
    result = send_invoice(inv, pdf_path, fmt_date, parse_date_any)

    if result["status"] == "sent":
        conn = get_db()
        conn.execute(
            "UPDATE invoices SET emailed_at = ?, emailed_to = ?, status = 'sent' WHERE id = ?",
            (datetime.now().isoformat(sep=' ', timespec='seconds'), result["to"], inv["id"])
        )
        conn.commit()
        conn.close()
        return {"status": "sent", "message": f"{number}: emailed to {result['to']}."}
    if result["status"] == "blocked":
        return {"status": "blocked", "message": f"{number}: email is switched off here (EMAIL_ENABLED)."}
    if result["status"] == "skipped":
        return {"status": "skipped", "message": f"{number}: {inv['student_name']} has no email address."}
    return {"status": "failed", "message": f"{number}: {result.get('message', 'Unknown error')}"}


# One invoice per request, so a long batch can't time out part-way (the list page sends them in turn).
@invoices_bp.route("/invoices/send/<int:invoice_id>", methods=["POST"])
def send_one_invoice(invoice_id):
    conn = get_db()
    inv = conn.execute(INVOICE_QUERY + " WHERE invoices.id = ?", (invoice_id,)).fetchone()
    conn.close()
    if not inv:
        return {"status": "failed", "message": f"Invoice {invoice_id} not found."}, 404
    try:
        return email_invoice(inv)
    except GmailNotConnected as e:
        return {"status": "gmail_not_connected", "message": f"{e} {GMAIL_HELP}"}, 503


# ---------------- Generate Invoice PDF ----------------
def generate_invoice_pdf(student_id, start_date, end_date, lessons, extras, total):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, parent, email FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()

    # Insert new invoice record, with its number and PDF filename
    cur.execute(
        "INSERT INTO invoices (student_id, start_date, end_date, total) VALUES (?, ?, ?, ?)",
        (student_id, start_date, end_date, total)
    )
    invoice_id = cur.lastrowid
    number = new_invoice_number(invoice_id)
    filename = f"{number}.pdf"
    cur.execute("UPDATE invoices SET invoice_number=?, pdf_filename=? WHERE id=?", (number, filename, invoice_id))
    conn.commit()
    conn.close()

    filepath = os.path.join(current_app.config["INVOICE_PDF_DIR"], filename)

    logo_path = os.path.join(
        current_app.root_path,
        current_app.config["STATIC_DIR"],
        current_app.config["LOGO_FILE"],
    )

    build_invoice_pdf(
        filepath=filepath,
        logo_path=logo_path,
        sender_email=current_app.config["SENDER_EMAIL"],
        sender_name=current_app.config["SENDER_NAME"],
        business_address_line1=current_app.config["BUSINESS_ADDRESS_LINE1"],
        business_address_line2=current_app.config["BUSINESS_ADDRESS_LINE2"],
        business_phone=current_app.config["BUSINESS_PHONE"],
        business_mobile=current_app.config["BUSINESS_MOBILE"],
        bank_account=current_app.config["BANK_ACCOUNT"],
        student_name=student["name"],
        student_email=student["email"],
        invoice_number=number,
        start_date_str=start_date,
        end_date_str=end_date,
        lessons=lessons,
        extras=extras,
        total=total,
        fmt_date=fmt_date,
    )

    flash(f"Invoice {number} generated successfully.", "success")
    return redirect(url_for("invoices_bp.invoice_list"))


# ---------------- Regenerate Invoice PDF ----------------
@invoices_bp.route("/invoices/pdf/<int:invoice_id>")
def regenerate_invoice_pdf(invoice_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,))
    invoice = cur.fetchone()
    conn.close()

    if not invoice:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoices_bp.invoice_list"))

    filename = pdf_filename_of(invoice)
    filepath = os.path.join(current_app.config["INVOICE_PDF_DIR"], filename)

    if not os.path.exists(filepath):
        flash("PDF file is missing on the server.", "warning")
        return redirect(url_for("invoices_bp.invoice_list"))

    return send_from_directory(current_app.config["INVOICE_PDF_DIR"], filename, as_attachment=False, mimetype="application/pdf")

