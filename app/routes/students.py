from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from db import get_db
from utils import DATETIME_FORMAT

students_bp = Blueprint("students_bp", __name__)

BLANK_SCHOOL = "__blank__"  # the school filter's value for students with no school


# ---------------- Back to the student list, keeping its filters ----------------
def back_to_list(form):
    filters = {key: form.get(f"return_{key}", "").strip() for key in ("show", "school", "q")}
    return redirect(url_for("students_bp.students", **{k: v for k, v in filters.items() if v}))


# ---------------- Create Student ----------------
@students_bp.route("/students", methods=["GET", "POST"])
def students():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        parent = request.form.get("parent", "")
        phone = request.form["phone"]
        school = request.form.get("school", "").strip()
        cur.execute(
            "INSERT INTO students (name, email, parent, phone, school) VALUES (?, ?, ?, ?, ?)",
            (name, email, parent, phone, school),
        )
        conn.commit()
        conn.close()
        flash("Student added successfully", "success")
        return redirect(url_for("students_bp.students"))

    # ---- Filters ----
    show = request.args.get("show", "current")  # current, archived or all
    school_filter = request.args.get("school", "").strip()
    q = request.args.get("q", "").strip()

    base_sql = """
        SELECT students.*,
               (SELECT COUNT(*) FROM invoices WHERE invoices.student_id = students.id) AS invoice_count,
               (SELECT COUNT(*) FROM lessons WHERE lessons.student_id = students.id) AS lesson_count
        FROM students WHERE 1=1
    """
    params = []
    if show == "archived":
        base_sql += " AND active = 0"
    elif show != "all":
        base_sql += " AND active = 1"
    if school_filter == BLANK_SCHOOL:
        base_sql += " AND COALESCE(school,'') = ''"
    elif school_filter:
        base_sql += " AND COALESCE(school,'') = ?"
        params.append(school_filter)
    if q:
        base_sql += " AND (LOWER(name) LIKE ? OR LOWER(email) LIKE ?)"
        params.extend([f"%{q.lower()}%", f"%{q.lower()}%"])
    base_sql += " ORDER BY name COLLATE NOCASE"

    cur.execute(base_sql, params)
    students = cur.fetchall()

    # For the school dropdown (read as tuples so we don't depend on row_factory)
    cur.execute("SELECT DISTINCT COALESCE(school,'') FROM students ORDER BY 1")
    school_options = [r[0] for r in cur.fetchall()]

    archived_count = cur.execute("SELECT COUNT(*) FROM students WHERE active = 0").fetchone()[0]

    conn.close()
    return render_template(
        "students.html",
        students=students,
        school_options=school_options,
        selected_school=school_filter,
        blank_school=BLANK_SCHOOL,
        q=q,
        show=show,
        archived_count=archived_count,
    )

# ---------------- Edit Student ----------------
@students_bp.route("/students/edit/<int:student_id>", methods=["POST"])
def edit_student(student_id):
    name = request.form["name"]
    email = request.form["email"]
    parent = request.form["parent"]
    phone = request.form["phone"]
    school = request.form.get("school", "").strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE students SET name=?, email=?, parent=?, phone=?, school=? WHERE id=?",
        (name, email, parent, phone, school, student_id),
    )
    conn.commit()
    conn.close()
    flash("Student updated successfully", "success")
    return back_to_list(request.form)

# ---------------- Archive / Restore Student ----------------
# Archived students keep their lessons and invoices, but aren't offered for new lessons or invoices.
@students_bp.route("/students/archive/<int:student_id>", methods=["POST"])
def archive_student(student_id):
    conn = get_db()
    student = conn.execute("SELECT name FROM students WHERE id=?", (student_id,)).fetchone()
    if student:
        conn.execute("UPDATE students SET active = 0, archived_at = ? WHERE id = ?",
                     (datetime.now().strftime(DATETIME_FORMAT), student_id))
        conn.commit()
        flash(f"{student['name']} archived. Their lessons and invoices are kept; "
              "use Show: Archived to find them again.", "success")
    else:
        flash("Student not found.", "danger")
    conn.close()
    return back_to_list(request.form)


@students_bp.route("/students/restore/<int:student_id>", methods=["POST"])
def restore_student(student_id):
    conn = get_db()
    student = conn.execute("SELECT name FROM students WHERE id=?", (student_id,)).fetchone()
    if student:
        conn.execute("UPDATE students SET active = 1, archived_at = NULL WHERE id = ?", (student_id,))
        conn.commit()
        flash(f"{student['name']} is a current student again.", "success")
    else:
        flash("Student not found.", "danger")
    conn.close()
    return back_to_list(request.form)

# ---------------- Delete Student ----------------
# Only for a student added by mistake: deleting also deletes their lessons, and would hide their invoices.
@students_bp.route("/students/delete/<int:student_id>", methods=["POST"])
def delete_student(student_id):
    conn = get_db()
    cur = conn.cursor()
    student = cur.execute("SELECT name FROM students WHERE id=?", (student_id,)).fetchone()
    invoice_count = cur.execute("SELECT COUNT(*) FROM invoices WHERE student_id=?", (student_id,)).fetchone()[0]
    if not student:
        flash("Student not found.", "danger")
    elif invoice_count:
        flash(f"{student['name']} has invoices, so they can't be deleted. Archive them instead.", "warning")
    else:
        cur.execute("DELETE FROM students WHERE id=?", (student_id,))
        conn.commit()
        flash(f"{student['name']} deleted.", "success")
    conn.close()
    return back_to_list(request.form)
