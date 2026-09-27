import os
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_from_directory

from db import get_db
from services.invoice_service import send_invoice
from services.pdf_service import build_invoice_pdf  # only if already needed here
from utils import build_invoice_filename, invoice_number, nz_school_term, parse_date_any, fmt_date

invoices_bp = Blueprint("invoices_bp", __name__)

# ---------------- Create Invoice ----------------
@invoices_bp.route("/invoices", methods=["GET", "POST"])
def invoices():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, name, parent, email FROM students ORDER BY name")
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
        previewed = True

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
                date_str = request.form.get(f"lesson_date_{i}")
                duration = request.form.get(f"lesson_duration_{i}")
                rate     = request.form.get(f"lesson_rate_{i}")
                if not (date_str and duration and rate):
                    continue
                duration_i = int(float(duration))
                rate_f = float(rate)
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
            desc = request.form.get(f"extra_desc_{i}")
            price = request.form.get(f"extra_price_{i}")
            if desc and price:
                price_f = float(price)
                extras.append({"desc": desc, "price": price_f})
                total += price_f

        if selection_changed:
            if action == "generate_pdf":
                flash("Not generated: the student or dates changed after the preview. "
                      "The lessons below have been reloaded; check them, then click Generate PDF again.", "warning")
            else:
                flash("Lessons reloaded for the new student or dates. "
                      "Edits and extra items from the previous preview were cleared.", "info")
        elif action == "generate_pdf":
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

    conn = get_db()
    cur = conn.cursor()

    current = cur.execute("SELECT status FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if current and current["status"] == "void":
        conn.close()
        flash(f"Invoice {invoice_id} is void. Restore it before changing its status.", "warning")
        return redirect_to_list(request.form)

    if new_status == "paid":
        # Default to now if no date provided
        if not paid_at:
            cur.execute("""
                UPDATE invoices
                   SET status='paid',
                       paid_at = datetime('now'),
                       paid_amount = COALESCE(?, paid_amount),
                       paid_ref = COALESCE(?, paid_ref)
                 WHERE id=?
            """, (float(paid_amt) if paid_amt else None,
                  paid_ref or None,
                  invoice_id))
        else:
            cur.execute("""
                UPDATE invoices
                   SET status='paid',
                       paid_at = ?,
                       paid_amount = COALESCE(?, paid_amount),
                       paid_ref = COALESCE(?, paid_ref)
                 WHERE id=?
            """, (paid_at,
                  float(paid_amt) if paid_amt else None,
                  paid_ref or None,
                  invoice_id))
    else:
        cur.execute("UPDATE invoices SET status=? WHERE id=?",
                    (new_status, invoice_id))

    conn.commit()
    conn.close()

    flash(f"Invoice {invoice_id} marked as {new_status}.", "success")
    return redirect_to_list(request.form)

# ---------------- Void / Restore Invoice ----------------
# A void invoice stays in the list for the record, but can't be emailed or marked paid.
@invoices_bp.route("/invoices/void/<int:invoice_id>", methods=["POST"])
def void_invoice(invoice_id):
    reason = request.form.get("void_reason", "").strip()
    conn = get_db()
    inv = conn.execute("SELECT status, created_at FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        flash("Invoice not found.", "danger")
    elif inv["status"] == "paid":
        flash("Paid invoices can't be voided.", "warning")
    else:
        conn.execute("UPDATE invoices SET status='void', voided_at=?, void_reason=? WHERE id=?",
                     (datetime.now().isoformat(sep=' ', timespec='seconds'), reason or None, invoice_id))
        conn.commit()
        flash(f"Invoice {invoice_number(inv['created_at'], invoice_id)} voided.", "success")
    conn.close()
    return redirect_to_list(request.form)


@invoices_bp.route("/invoices/restore/<int:invoice_id>", methods=["POST"])
def restore_invoice(invoice_id):
    conn = get_db()
    inv = conn.execute("SELECT created_at FROM invoices WHERE id=? AND status='void'", (invoice_id,)).fetchone()
    if inv:
        conn.execute("""UPDATE invoices
                           SET status = CASE WHEN emailed_at IS NULL THEN 'draft' ELSE 'sent' END,
                               voided_at = NULL, void_reason = NULL
                         WHERE id=?""", (invoice_id,))
        conn.commit()
        flash(f"Invoice {invoice_number(inv['created_at'], invoice_id)} restored.", "success")
    conn.close()
    return redirect_to_list(request.form)

# ---------------- Invoice List ----------------
@invoices_bp.route("/invoices/list", methods=["GET", "POST"])
def invoice_list():
    conn = get_db()
    cur = conn.cursor()

    # Student list for filter dropdown
    cur.execute("SELECT id, name FROM students ORDER BY name")
    student_options = cur.fetchall()

    # Filters
    student_id = request.args.get("student_id")
    start_date = request.args.get("start_date")
    end_date   = request.args.get("end_date")
    status     = request.args.get("status", "")
    term_filter = request.args.get("term", "")   # 'T1'/'T2'/'T3'/'T4' or ''
    year        = request.args.get("year", "")   # '2025', etc., or ''

    # Build query (include new columns for UI)
    query = """
        SELECT invoices.id, invoices.start_date, invoices.end_date,
               invoices.total, invoices.created_at,
               invoices.emailed_at, invoices.emailed_to,
               invoices.status, invoices.paid_at, invoices.paid_amount, invoices.paid_ref,
               invoices.voided_at, invoices.void_reason,
               students.id AS student_id,
               students.name AS student_name,
               students.parent AS parent_name,
               students.email AS student_email
        FROM invoices
        JOIN students ON invoices.student_id = students.id
        WHERE 1=1
    """
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

            st = inv["status"] or ("sent" if inv["emailed_at"] else "draft")
            if st in ("paid", "void"):
                skipped += 1
                errors.append(f"Invoice {sid}: {st}, so not emailed.")
                continue

            filename = build_invoice_filename(inv["created_at"], inv["id"])
            pdf_path = os.path.join(current_app.config["INVOICE_PDF_DIR"], filename)   

            result = send_invoice(inv, pdf_path, fmt_date, parse_date_any)

            if result["status"] == "sent":
                sent += 1

                conn2 = get_db()
                cur2 = conn2.cursor()
                cur2.execute(
                    "UPDATE invoices SET emailed_at = ?, emailed_to = ?, status = 'sent' WHERE id = ?",
                    (datetime.now().isoformat(sep=' ', timespec='seconds'), result["to"], inv["id"])
                )
                conn2.commit()
                conn2.close()

            elif result["status"] == "blocked":
                skipped += 1
                errors.append(f"Invoice {sid}: email blocked in development mode.")

            elif result["status"] == "skipped":
                skipped += 1
                errors.append(f"Invoice {sid}: no email address.")

            else:
                failed += 1
                errors.append(f"Invoice {sid}: {result.get('message', 'Unknown error')}")

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

# ---------------- Generate Invoice PDF ----------------
def generate_invoice_pdf(student_id, start_date, end_date, lessons, extras, total):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name, parent, email FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()

    # Insert new invoice record
    cur.execute(
        "INSERT INTO invoices (student_id, start_date, end_date, total) VALUES (?, ?, ?, ?)",
        (student_id, start_date, end_date, total)
    )
    conn.commit()
    invoice_id = cur.lastrowid
    conn.close()

    invoice_number = f"INV-{datetime.now().year}-{invoice_id:04d}"
    filename = f"{invoice_number}.pdf"
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
        invoice_number=invoice_number,
        start_date_str=start_date,
        end_date_str=end_date,
        lessons=lessons,
        extras=extras,
        total=total,
        fmt_date=fmt_date,
    )

    flash(f"Invoice {invoice_number} generated successfully.", "success")
    return redirect(url_for("invoices_bp.invoice_list"))


# ---------------- Regenerate Invoice PDF ----------------
@invoices_bp.route("/invoices/pdf/<int:invoice_id>")
def regenerate_invoice_pdf(invoice_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT created_at FROM invoices WHERE id=?", (invoice_id,))
    invoice = cur.fetchone()
    conn.close()

    if not invoice:
        flash("Invoice not found.", "danger")
        return redirect(url_for("invoices_bp.invoice_list"))

    year = invoice["created_at"][:4] if invoice["created_at"] else str(datetime.now().year)
    invoice_number = f"INV-{year}-{invoice_id:04d}"
    filename = f"{invoice_number}.pdf"
    filepath = os.path.join(current_app.config["INVOICE_PDF_DIR"], filename)

    if not os.path.exists(filepath):
        flash("PDF file is missing on the server.", "warning")
        return redirect(url_for("invoices_bp.invoice_list"))

    return send_from_directory(current_app.config["INVOICE_PDF_DIR"], filename, as_attachment=False, mimetype="application/pdf")

