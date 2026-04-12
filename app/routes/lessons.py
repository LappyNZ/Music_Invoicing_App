from flask import Blueprint, render_template, request, redirect, url_for, flash
from db import get_db
from datetime import datetime, timedelta

lessons_bp = Blueprint("lessons_bp", __name__)

# ---------------- Create Lesson ----------------
@lessons_bp.route("/lessons", methods=["GET", "POST"])
def lessons():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        student_id = request.form["student_id"]
        lesson_time_str = request.form["lesson_time"]  # e.g. "2025-08-20T14:00"
        duration = int(request.form["duration"])
        rate = float(request.form["rate"])
        repeat_weeks = int(request.form.get("repeat_weeks", 1))

        start_dt = datetime.strptime(lesson_time_str, "%Y-%m-%dT%H:%M")

        for i in range(repeat_weeks):
            dt = start_dt + timedelta(weeks=i)
            cur.execute("""
                INSERT INTO lessons (student_id, lesson_time, duration, rate)
                VALUES (?, ?, ?, ?)
            """, (student_id, dt.strftime("%Y-%m-%d %H:%M"), duration, rate))

        conn.commit()
        conn.close()
        flash("Lesson(s) added successfully", "success")
        return redirect(url_for("lessons_bp.lessons"))

    # --- Filtering ---
    student_filter = request.args.get("student_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = """
        SELECT
          lessons.id,
          lessons.student_id,
          students.name AS student_name,
          lessons.lesson_time,
          lessons.duration,
          lessons.rate
        FROM lessons
        JOIN students ON lessons.student_id = students.id
        WHERE 1=1
    """
    params = []

    if student_filter:
        query += " AND students.id = ?"
        params.append(student_filter)
    if start_date:
        query += " AND lessons.lesson_time >= ?"
        params.append(start_date)
    if end_date:
        query += " AND lessons.lesson_time <= ?"
        params.append(end_date)

    query += " ORDER BY lessons.lesson_time"
    cur.execute(query, params)
    lessons = [dict(row) for row in cur.fetchall()]

    # Format date
    for lesson in lessons:
        try:
            dt = datetime.strptime(lesson["lesson_time"], "%Y-%m-%d %H:%M")
            # Linux format flags (inside Docker)
            lesson["formatted_time"] = dt.strftime("%a, %-d %b %y, %-I:%M%p")
        except ValueError:
            lesson["formatted_time"] = lesson["lesson_time"]

    # Fetch students for dropdown
    cur.execute("SELECT id, name FROM students ORDER BY name")
    students = cur.fetchall()

    conn.close()
    return render_template(
        "lessons.html",
        lessons=lessons,
        students=students,
        selected_student=student_filter,
        start_date=start_date,
        end_date=end_date,
    )

# ---------------- Edit Lesson ----------------
@lessons_bp.route("/lessons/edit/<int:lesson_id>", methods=["POST"])
def edit_lesson(lesson_id):
    student_id = request.form["student_id"]
    lesson_time = request.form["lesson_time"]
    duration = request.form["duration"]
    rate = request.form["rate"]

    # capture filters for redirect
    ret_student = request.form.get("return_student_id", "").strip()
    ret_start   = request.form.get("return_start_date", "").strip()
    ret_end     = request.form.get("return_end_date", "").strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""UPDATE lessons 
                   SET student_id=?, lesson_time=?, duration=?, rate=? 
                   WHERE id=?""",
                (student_id, lesson_time, duration, rate, lesson_id))
    conn.commit()
    conn.close()
    flash("Lesson updated successfully", "success")

    # rebuild query string only with non-empty filters
    qs = {}
    if ret_student: qs["student_id"] = ret_student
    if ret_start:   qs["start_date"] = ret_start
    if ret_end:     qs["end_date"]   = ret_end
    return redirect(url_for("lessons_bp.lessons", **qs))

# ---------------- Delete Lesson ----------------
@lessons_bp.route("/lessons/delete/<int:lesson_id>", methods=["POST"])
def delete_lesson(lesson_id):

    # capture filters for redirect
    ret_student = request.form.get("return_student_id", "").strip()
    ret_start   = request.form.get("return_start_date", "").strip()
    ret_end     = request.form.get("return_end_date", "").strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
    conn.commit()
    conn.close()
    flash("Lesson deleted successfully", "success")
    qs = {}
    if ret_student: qs["student_id"] = ret_student
    if ret_start:   qs["start_date"] = ret_start
    if ret_end:     qs["end_date"]   = ret_end
    return redirect(url_for("lessons_bp.lessons", **qs))
