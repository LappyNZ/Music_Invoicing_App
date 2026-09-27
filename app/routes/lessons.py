import math

from flask import Blueprint, render_template, request, redirect, url_for, flash
from db import get_db
from datetime import date, datetime, timedelta

from utils import DATETIME_FORMAT, parse_datetime

lessons_bp = Blueprint("lessons_bp", __name__)

# When the page is first opened it shows recent and coming lessons, not every lesson ever stored.
SHOW_WEEKS_BEFORE, SHOW_WEEKS_AFTER = 4, 13


def display_time(when: datetime) -> str:
    try:
        return when.strftime("%a, %-d %b %y, %-I:%M%p")  # Linux (inside Docker)
    except ValueError:
        return when.strftime("%a, %d %b %y, %I:%M%p")    # Windows


def read_lesson_form(form):
    """(time, duration, rate) from the add or edit form, or None and what's wrong with it."""
    when = parse_datetime(form.get("lesson_time"))
    if when is None:
        return None, "The lesson time wasn't understood."
    try:
        duration, rate = int(form.get("duration", "")), float(form.get("rate", ""))
    except ValueError:
        duration = rate = -1
    if duration <= 0 or not (math.isfinite(rate) and rate >= 0):
        return None, "Duration and rate must be numbers, e.g. 30 and 60.00."
    return (when, duration, rate), None


def back_to_list(form):
    """Back to the lesson list, showing the same student and dates as before."""
    filters = {"start_date": form.get("return_start_date", "").strip(),
               "end_date": form.get("return_end_date", "").strip()}
    student = form.get("return_student_id", "").strip()
    if student:
        filters["student_id"] = student
    return redirect(url_for("lessons_bp.lessons", **filters))


# ---------------- Create Lesson ----------------
@lessons_bp.route("/lessons", methods=["GET", "POST"])
def lessons():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        student_id = request.form["student_id"]
        repeat_weeks = max(1, int(request.form.get("repeat_weeks") or 1))  # blank means just this week
        lesson, problem = read_lesson_form(request.form)
        if problem:
            flash(f"{problem} Nothing was added.", "danger")
            conn.close()
            return redirect(url_for("lessons_bp.lessons"))
        start_dt, duration, rate = lesson

        for i in range(repeat_weeks):
            dt = start_dt + timedelta(weeks=i)
            cur.execute("""
                INSERT INTO lessons (student_id, lesson_time, duration, rate)
                VALUES (?, ?, ?, ?)
            """, (student_id, dt.strftime(DATETIME_FORMAT), duration, rate))

        conn.commit()
        conn.close()
        flash("Lesson(s) added successfully", "success")
        return redirect(url_for("lessons_bp.lessons"))

    # --- Filtering ---
    student_filter = request.args.get("student_id", "")
    if "start_date" in request.args or "end_date" in request.args:
        start_date = request.args.get("start_date", "")  # blank means no limit
        end_date = request.args.get("end_date", "")
    else:
        today = date.today()
        start_date = (today - timedelta(weeks=SHOW_WEEKS_BEFORE)).isoformat()
        end_date = (today + timedelta(weeks=SHOW_WEEKS_AFTER)).isoformat()

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

    # Lessons whose time can't be read have no date, so they're shown whatever the dates, to be fixed.
    if student_filter:
        query += " AND students.id = ?"
        params.append(student_filter)
    if start_date:
        query += " AND (date(lessons.lesson_time) >= date(?) OR date(lessons.lesson_time) IS NULL)"
        params.append(start_date)
    if end_date:
        query += " AND (date(lessons.lesson_time) <= date(?) OR date(lessons.lesson_time) IS NULL)"
        params.append(end_date)

    query += " ORDER BY date(lessons.lesson_time) IS NOT NULL, lessons.lesson_time"
    cur.execute(query, params)
    lessons = [dict(row) for row in cur.fetchall()]

    for lesson in lessons:
        when = parse_datetime(lesson["lesson_time"])
        lesson["unreadable"] = when is None
        lesson["formatted_time"] = display_time(when) if when else lesson["lesson_time"]
        lesson["input_time"] = when.strftime("%Y-%m-%dT%H:%M") if when else ""  # for the date-time picker

    # Fetch students for dropdowns (archived ones only in the filter and edit boxes)
    cur.execute("SELECT id, name, active FROM students ORDER BY name")
    students = cur.fetchall()

    conn.close()
    return render_template(
        "lessons.html",
        lessons=lessons,
        students=students,
        selected_student=student_filter,
        start_date=start_date,
        end_date=end_date,
        unreadable_count=sum(lesson["unreadable"] for lesson in lessons),
    )

# ---------------- Edit Lesson ----------------
@lessons_bp.route("/lessons/edit/<int:lesson_id>", methods=["POST"])
def edit_lesson(lesson_id):
    lesson, problem = read_lesson_form(request.form)
    if problem:
        flash(f"{problem} Nothing was changed.", "danger")
        return back_to_list(request.form)
    when, duration, rate = lesson

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""UPDATE lessons
                   SET student_id=?, lesson_time=?, duration=?, rate=?
                   WHERE id=?""",
                (request.form["student_id"], when.strftime(DATETIME_FORMAT), duration, rate, lesson_id))
    conn.commit()
    conn.close()
    flash("Lesson updated successfully", "success")
    return back_to_list(request.form)

# ---------------- Delete Lesson ----------------
@lessons_bp.route("/lessons/delete/<int:lesson_id>", methods=["POST"])
def delete_lesson(lesson_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
    conn.commit()
    conn.close()
    flash("Lesson deleted successfully", "success")
    return back_to_list(request.form)
