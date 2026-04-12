from flask import Blueprint, render_template, request, redirect, url_for, flash
from db import get_db

students_bp = Blueprint("students_bp", __name__)

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
    school_filter = request.args.get("school", "").strip()
    q = request.args.get("q", "").strip()

    base_sql = "SELECT * FROM students WHERE 1=1"
    params = []
    if school_filter:
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

    conn.close()
    return render_template(
        "students.html",
        students=students,
        school_options=school_options,
        selected_school=school_filter,
        q=q,
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
    return redirect(url_for("students_bp.students"))

# ---------------- Delete Student ----------------
@students_bp.route("/students/delete/<int:student_id>", methods=["POST"])
def delete_student(student_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE id=?", (student_id,))
    conn.commit()
    conn.close()
    flash("Student deleted successfully", "success")
    return redirect(url_for("students_bp.students"))