from datetime import datetime, time, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import billing as B
import terms as T
from db import get_db
from utils import DATETIME_FORMAT, DAY_NAMES, DAYS, fmt_clock, fmt_day, fmt_dm, fmt_long, lesson_cents, money

register_bp = Blueprint("register_bp", __name__)

WORDS = {"taught": "had lesson", "cancelled": "cancelled, no charge", "missed": "missed, still charged", "holiday": "holiday"}
SYMBOLS = {"taught": "✓", "cancelled": "✗", "missed": "$", "holiday": "Hol"}
NEXT = {"taught": "cancelled", "cancelled": "missed", "missed": "taught", "holiday": "holiday"}


def wants_json():
    return request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json"


def back(term_id, week=None, view=None, anchor=""):
    url = url_for("register_bp.register", term=term_id, week=week, view="term" if view == "term" else None)
    return redirect(url + (f"#{anchor}" if anchor else ""))


def form_back(anchor=""):
    f = request.form
    return back(f.get("term", type=int), f.get("week", type=int), f.get("view"), anchor)


def billed_note(lesson):
    """Which invoice a lesson is on, when that matters to someone changing it."""
    if not lesson["invoice_id"] or not lesson["invoice_number"]:
        return ""
    if lesson["invoice_status"] in ("draft", "revising"):
        return f"On draft {lesson['invoice_number']}"
    return f"On {lesson['invoice_number']} (sent)"


def active_students(conn):
    return conn.execute("SELECT * FROM students WHERE active = 1 ORDER BY name").fetchall()


# ---------------------------------------------------------------- the register

@register_bp.route("/register")
def register():
    conn = get_db()
    today = T.today()
    terms = T.all_terms(conn)
    term = T.get_term(conn, request.args.get("term", type=int) or 0) or T.current_term(conn, today)
    if not term:
        conn.close()
        return render_template("register.html", term=None, terms=[])
    term_weeks, weeks = T.term_weeks(term), T.register_weeks(conn, term)
    checked = T.checked_weeks(conn, term)
    view = "term" if request.args.get("view") == "term" else "week"
    week = request.args.get("week", type=int)
    if not week:
        in_term = T.day(term["start_date"]) <= today <= T.day(term["end_date"])
        week = T.week_of(term, today) if in_term else next((w for w in range(1, term_weeks + 1) if w not in checked), 1)
    week = max(1, min(week, weeks))
    ctx = dict(term=term, terms=terms, view=view, week=week, weeks=weeks, term_weeks=term_weeks, checked=checked,
               week_list=[{"n": w, "start": T.week_start(term, w), "checked": w in checked, "holidays": w > term_weeks}
                          for w in range(1, weeks + 1)],
               students=active_students(conn), fmt_dm=fmt_dm, fmt_day=fmt_day, symbols=SYMBOLS, words=WORDS, days=DAY_NAMES,
               started=bool(term["started_at"]), future=T.day(term["start_date"]) > today)
    if view == "term":
        ctx.update(grid(conn, term, weeks))
    else:
        ctx.update(week_view(conn, term, week))
    conn.close()
    return render_template("register.html", **ctx)


def week_view(conn, term, week):
    holidays = T.holidays(conn, term)
    days = {}
    for lesson in T.week_lessons(conn, term, week):
        lesson["time_text"] = fmt_clock(lesson["when"])
        lesson["billed"] = billed_note(lesson)
        days.setdefault(lesson["when"].date(), []).append(lesson)
    start = T.week_start(term, week)
    unchecked_after = [w for w in range(week + 1, T.term_weeks(term) + 1) if w not in T.checked_weeks(conn, term)]
    return {
        "day_groups": [{"date": d, "title": fmt_long(d), "holiday": holidays.get(d.isoformat()), "lessons": ls,
                        "cancellable": sum(1 for x in ls if x["status"] == "taught")} for d, ls in sorted(days.items())],
        "week_dates": [start + timedelta(days=i) for i in range(7)],
        "week_start": start, "week_end": start + timedelta(days=6),
        "next_unchecked": unchecked_after[0] if unchecked_after else None,
    }


def grid(conn, term, weeks):
    rows = {}
    for lesson in T.term_lessons(conn, term):
        w = T.week_of(term, lesson["when"].date())
        row = rows.setdefault(lesson["student_id"], {"id": lesson["student_id"], "name": lesson["student_name"], "cells": {},
                                                     "order": (lesson["when"].isoweekday(), lesson["when"].strftime("%H:%M")),
                                                     "count": 0, "cents": 0, "slot": ""})
        row["cells"].setdefault(w, []).append(lesson)
        if lesson["status"] in B.CHARGED:
            row["count"] += 1
            row["cents"] += lesson_cents(lesson["duration"], lesson["rate"])
        if not row["slot"] and lesson["kind"] == "regular":
            row["slot"] = f"{DAYS[lesson['when'].weekday()]} {fmt_clock(lesson['when'])} · {lesson['duration']} min"
    ordered = sorted(rows.values(), key=lambda r: (r["order"], r["name"]))
    return {"grid_rows": ordered, "grid_count": sum(r["count"] for r in ordered), "grid_cents": sum(r["cents"] for r in ordered),
            "money": money}


def lesson_or_404(conn, lesson_id):
    lesson = conn.execute(T.LESSON_QUERY + " WHERE lessons.id=?", (lesson_id,)).fetchone()
    if not lesson:
        conn.close()
        return None
    return lesson


@register_bp.route("/register/lesson/<int:lesson_id>/status", methods=["POST"])
def set_status(lesson_id):
    conn = get_db()
    status = request.form.get("status", "")
    lesson = B.set_lesson_status(conn, lesson_id, status)
    conn.commit()
    conn.close()
    if wants_json():
        return (jsonify({"ok": True, "status": lesson["status"]}) if lesson else (jsonify({"ok": False}), 404))
    return form_back(f"lesson-{lesson_id}")


@register_bp.route("/register/lesson/<int:lesson_id>/cycle", methods=["POST"])
def cycle(lesson_id):
    conn = get_db()
    current = conn.execute("SELECT status FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    lesson = B.set_lesson_status(conn, lesson_id, NEXT[current["status"]]) if current else None
    conn.commit()
    conn.close()
    if wants_json():
        if not lesson:
            return jsonify({"ok": False}), 404
        return jsonify({"ok": True, "status": lesson["status"], "symbol": SYMBOLS[lesson["status"]], "words": WORDS[lesson["status"]]})
    return form_back()


def read_lesson_form(f):
    """(when, minutes, rate, note) from an add or edit form, or a message saying what's wrong."""
    try:
        when = datetime.strptime(f"{f.get('date', '')} {f.get('time', '')}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None, "The day or time wasn’t understood."
    try:
        minutes, rate = int(f.get("minutes", "")), float(f.get("rate", ""))
    except ValueError:
        return None, "Length and rate need to be numbers, e.g. 30 and 70."
    if not (5 <= minutes <= 240) or not (0 <= rate <= 1000):
        return None, "Length and rate need to be numbers, e.g. 30 and 70."
    return (when, minutes, rate, f.get("note", "").strip() or None), None


@register_bp.route("/register/lesson/<int:lesson_id>/edit", methods=["POST"])
def edit_lesson(lesson_id):
    conn = get_db()
    lesson = lesson_or_404(conn, lesson_id)
    if not lesson:
        flash("That lesson isn’t there any more.", "warning")
        return form_back()
    values, problem = read_lesson_form(request.form)
    if problem:
        conn.close()
        flash(f"{problem} Nothing was changed.", "warning")
        return form_back(f"lesson-{lesson_id}")
    when, minutes, rate, note = values
    kind = None    # unchanged, unless the form has the "Extra lesson" box
    if request.form.get("kind_field"):
        kind = "extra" if request.form.get("extra") == "1" else "regular"
    conn.execute("UPDATE lessons SET lesson_time=?, duration=?, rate=?, note=?, kind=COALESCE(?, kind) WHERE id=?",
                 (when.strftime(DATETIME_FORMAT), minutes, rate, note, kind, lesson_id))
    if lesson["invoice_id"]:
        B.refresh_total(conn, lesson["invoice_id"])
    conn.commit()
    conn.close()
    flash("Lesson changed." + (f" It’s on {lesson['invoice_number']}, which has been sent: open it to correct and resend."
                               if lesson["invoice_status"] in ("sent", "paid") else ""), "success")
    return form_back(f"lesson-{lesson_id}")


@register_bp.route("/register/lesson/<int:lesson_id>/delete", methods=["POST"])
def delete_lesson(lesson_id):
    conn = get_db()
    lesson = lesson_or_404(conn, lesson_id)
    if lesson:
        conn.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
        if lesson["invoice_id"]:
            B.refresh_total(conn, lesson["invoice_id"])
        conn.commit()
        conn.close()
        flash(f"Lesson deleted for {lesson['student_name']}.", "success")
    return form_back()


def rate_for(conn, student):
    if student["lesson_rate"] is not None:
        return student["lesson_rate"]
    last = conn.execute("SELECT rate FROM lessons WHERE student_id=? ORDER BY lesson_time DESC LIMIT 1", (student["id"],)).fetchone()
    return last[0] if last else 70


@register_bp.route("/register/extra", methods=["POST"])
def add_extra():
    conn = get_db()
    student = conn.execute("SELECT * FROM students WHERE id=?", (request.form.get("student_id", type=int) or 0,)).fetchone()
    form = dict(request.form)
    if student and not form.get("rate"):
        form["rate"] = str(rate_for(conn, student))
    values, problem = read_lesson_form(form)
    if not student or problem:
        conn.close()
        flash(f"{problem or 'Choose a student.'} Nothing was added.", "warning")
        return form_back()
    when, minutes, rate, note = values
    cur = conn.execute("INSERT INTO lessons (student_id, lesson_time, duration, rate, status, kind, note) VALUES (?, ?, ?, ?, 'taught', 'extra', ?)",
                       (student["id"], when.strftime(DATETIME_FORMAT), minutes, rate, note))
    conn.commit()
    conn.close()
    flash(f"Extra lesson added for {student['name']}, {fmt_day(when)} {fmt_clock(when)}.", "success")
    return form_back(f"lesson-{cur.lastrowid}")


@register_bp.route("/register/weekly", methods=["POST"])
def add_weekly():
    """A student's regular lesson every week for the rest of the term (e.g. someone starting mid-term)."""
    conn = get_db()
    f = request.form
    term = T.get_term(conn, f.get("term", type=int) or 0)
    student = conn.execute("SELECT * FROM students WHERE id=?", (f.get("student_id", type=int) or 0,)).fetchone()
    try:
        day, first_week = int(f.get("day", "")), int(f.get("from_week", ""))
        start = time.fromisoformat(f.get("time", ""))
    except ValueError:
        day = first_week = start = None
    minutes_rate, problem = read_lesson_form({"date": "2000-01-01", "time": f.get("time", ""), "minutes": f.get("minutes", ""),
                                              "rate": f.get("rate", ""), "note": ""})
    if not term or not student or day is None or problem:
        conn.close()
        flash(f"{problem or 'Choose a student, day and time.'} Nothing was added.", "warning")
        return form_back()
    _, minutes, rate, _ = minutes_rate
    added = add_weekly_lessons(conn, term, student["id"], day, start, minutes, rate, first_week)
    conn.execute("UPDATE students SET lesson_day=?, lesson_start=?, lesson_minutes=?, lesson_rate=? WHERE id=?",
                 (day, start.strftime("%H:%M"), minutes, rate, student["id"]))
    conn.commit()
    conn.close()
    flash(f"{added} weekly lessons added for {student['name']}.", "success")
    return form_back()


def add_weekly_lessons(conn, term, student_id, day, start, minutes, rate, first_week=1):
    holidays = T.holidays(conn, term)
    added = 0
    for week in range(max(1, first_week), T.term_weeks(term) + 1):
        d = T.week_start(term, week) + timedelta(days=day - 1)
        if d > T.day(term["end_date"]):
            continue
        stamp = datetime.combine(d, start).strftime(DATETIME_FORMAT)
        if conn.execute("SELECT 1 FROM lessons WHERE student_id=? AND lesson_time=?", (student_id, stamp)).fetchone():
            continue
        conn.execute("INSERT INTO lessons (student_id, lesson_time, duration, rate, status, kind) VALUES (?, ?, ?, ?, ?, 'regular')",
                     (student_id, stamp, minutes, rate, "holiday" if d.isoformat() in holidays else "taught"))
        added += 1
    return added


@register_bp.route("/register/day/cancel", methods=["POST"])
def cancel_day():
    conn = get_db()
    day = request.form.get("date", "")
    lessons = conn.execute("SELECT id FROM lessons WHERE date(lesson_time)=? AND status='taught'", (day,)).fetchall() if T.valid_date(day) else []
    for lesson in lessons:
        B.set_lesson_status(conn, lesson["id"], "cancelled")
    conn.commit()
    conn.close()
    if lessons:
        flash(f"All {len(lessons)} lessons on {fmt_long(T.day(day))} marked cancelled, no charge.", "success")
    return form_back()


@register_bp.route("/register/week", methods=["POST"])
def check_week():
    conn = get_db()
    term = T.get_term(conn, request.form.get("term", type=int) or 0)
    week = request.form.get("week", type=int) or 1
    done = request.form.get("checked") == "1"
    T.set_week_checked(conn, term, week, done)
    conn.commit()
    checked = T.checked_weeks(conn, term)
    conn.close()
    if not done:
        return back(term["id"], week)
    remaining = [w for w in range(1, T.term_weeks(term) + 1) if w not in checked]
    if not remaining:
        flash(f"Every week of {term['name']} is checked.", "success")
        return back(term["id"], week)
    following = next((w for w in remaining if w > week), remaining[0])
    flash(f"Week {week} done.", "success")
    return back(term["id"], following)


# ---------------------------------------------------------------- starting a term

def lessons_after(conn, term, end):
    """Lessons entered for the holidays after the term and not billed: usually left over from repeating weeks."""
    following = T.next_term(conn, term) if term else None
    limit = T.day(following["start_date"]) - timedelta(days=1) if following else end + timedelta(weeks=T.HOLIDAY_WEEKS)
    return conn.execute("""SELECT id, lesson_time FROM lessons WHERE date(lesson_time) > ? AND date(lesson_time) <= ?
                             AND invoice_id IS NULL AND kind = 'regular' ORDER BY lesson_time""",
                        (end.isoformat(), limit.isoformat())).fetchall()


def plan_term(conn, term, start, end, holidays, rows):
    """What starting the term would do. `rows` are the students' choices from the form."""
    existing = {r[0]: r[1] for r in conn.execute("""SELECT student_id, COUNT(*) FROM lessons WHERE date(lesson_time) BETWEEN ? AND ?
                                                    GROUP BY student_id""", (start.isoformat(), end.isoformat()))}
    new_lessons = on_holidays = 0
    for row in rows:
        row["existing"] = existing.get(row["id"], 0)
        if not row["include"] or row["existing"] or not row["valid"]:
            continue
        for week in range((end - T.monday_of(start)).days // 7 + 1):
            d = T.monday_of(start) + timedelta(weeks=week, days=row["day"] - 1)
            if start <= d <= end:
                if d.isoformat() in holidays:
                    on_holidays += 1
                else:
                    new_lessons += 1
    already_on_holidays = conn.execute(f"""SELECT COUNT(*) FROM lessons WHERE status='taught' AND kind='regular'
                                          AND date(lesson_time) IN ({','.join('?' * len(holidays)) or "''"})""",
                                       tuple(holidays)).fetchone()[0]
    after = lessons_after(conn, term, end)
    return {"new_lessons": new_lessons, "on_holidays": on_holidays + already_on_holidays,
            "students": sum(1 for r in rows if r["include"] and r["valid"] and not r["existing"]),
            "already": [r for r in rows if r["existing"]], "after": len(after),
            "after_from": T.day(after[0]["lesson_time"]) if after else None, "after_to": T.day(after[-1]["lesson_time"]) if after else None}


def student_rows(conn, form=None):
    rows = []
    for s in active_students(conn):
        sid = s["id"]
        get = (lambda k, default: form.get(f"{k}_{sid}", default)) if form is not None else (lambda k, default: default)
        day, start, minutes, rate = get("day", s["lesson_day"] or ""), get("time", s["lesson_start"] or ""), \
            get("minutes", s["lesson_minutes"] or ""), get("rate", "%g" % s["lesson_rate"] if s["lesson_rate"] is not None else "")
        try:
            day_n, start_t, minutes_n, rate_n = int(day), time.fromisoformat(str(start)), int(minutes), float(rate)
            valid = 1 <= day_n <= 7 and 5 <= minutes_n <= 240 and 0 <= rate_n <= 1000
        except (TypeError, ValueError):
            day_n, start_t, minutes_n, rate_n, valid = None, None, None, None, False
        include = (form.get(f"include_{sid}") == "1") if form is not None else valid
        rows.append({"id": sid, "name": s["name"], "day": day_n, "time": start, "time_t": start_t, "minutes": minutes,
                     "minutes_n": minutes_n, "rate": rate, "rate_n": rate_n, "valid": valid, "include": include,
                     "old_rate": s["lesson_rate"]})
    return rows


@register_bp.route("/terms/start", methods=["GET", "POST"])
def start_term():
    conn = get_db()
    today = T.today()
    term = T.get_term(conn, request.values.get("term", type=int) or 0) or conn.execute(
        "SELECT * FROM terms WHERE start_date > ? AND started_at IS NULL ORDER BY start_date LIMIT 1", (today.isoformat(),)).fetchone()
    if term:
        name, start, end = term["name"], T.day(term["start_date"]), T.day(term["end_date"])
    else:
        name, start, end = T.suggest_next_term(conn)
    f = request.form if request.method == "POST" else None
    problems = []
    if f is not None:
        name = f.get("name", name).strip() or name
        if T.valid_date(f.get("start")) and T.valid_date(f.get("end")):
            start, end = T.day(f["start"]), T.day(f["end"])
        else:
            problems.append("The first and last days need to be dates.")
    if end < start or (end - start).days > 7 * 16:
        problems.append("The last day needs to be after the first day, and a term can’t be longer than 16 weeks.")
    clash = conn.execute("SELECT name FROM terms WHERE start_date=? AND id IS NOT ?", (start.isoformat(), term["id"] if term else None)).fetchone()
    if clash:
        problems.append(f"{clash['name']} already starts that day.")

    saved = T.holidays(conn, term) if term else {}
    known = {d: n for d, n in T.KNOWN_HOLIDAYS.items() if start.isoformat() <= d <= end.isoformat()} | saved
    if f is None:
        chosen = dict(saved) if term and term["started_at"] else dict(known)
    else:
        for key, value in f.items():     # days off added on an earlier "check" of this page
            if key.startswith("holname_") and T.valid_date(key[8:]) and value.strip():
                known[key[8:]] = value.strip()
        added = {}
        for i in range(3):
            d, n = f.get(f"extra_date_{i}", ""), f.get(f"extra_name_{i}", "").strip()
            if T.valid_date(d):
                added[d] = n or "Day off"
        known.update(added)
        chosen = {d: n for d, n in known.items() if f.get(f"hol_{d}") == "1"} | added
    holiday_rows = [{"date": T.day(d), "iso": d, "name": n, "on": d in chosen} for d, n in sorted(known.items())]

    rows = student_rows(conn, f)
    plan = plan_term(conn, term, start, end, chosen, rows)
    action = f.get("action") if f is not None else None
    if action == "start" and not problems:
        drop_after = f.get("drop_after") == "1"
        after = lessons_after(conn, term, end) if drop_after else []
        if term:
            conn.execute("UPDATE terms SET name=?, start_date=?, end_date=? WHERE id=?", (name, start.isoformat(), end.isoformat(), term["id"]))
            term = T.get_term(conn, term["id"])
        else:
            term = T.add_term(conn, name, start, end)
        for d in saved:
            if d not in chosen:     # no longer a day off: its lessons happen after all
                conn.execute("UPDATE lessons SET status='taught' WHERE date(lesson_time)=? AND status='holiday'", (d,))
        conn.execute("DELETE FROM term_holidays WHERE term_id=?", (term["id"],))
        for d, n in chosen.items():
            conn.execute("INSERT INTO term_holidays (term_id, date, name) VALUES (?, ?, ?)", (term["id"], d, n))
            conn.execute("UPDATE lessons SET status='holiday' WHERE date(lesson_time)=? AND status='taught' AND kind='regular'", (d,))
        for row in rows:
            if not row["valid"]:
                continue
            conn.execute("UPDATE students SET lesson_day=?, lesson_start=?, lesson_minutes=?, lesson_rate=? WHERE id=?",
                         (row["day"], row["time_t"].strftime("%H:%M"), row["minutes_n"], row["rate_n"], row["id"]))
            if row["existing"] and row["rate_n"] != row["old_rate"]:
                conn.execute("""UPDATE lessons SET rate=? WHERE student_id=? AND kind='regular' AND date(lesson_time) BETWEEN ? AND ?
                                  AND (invoice_id IS NULL OR invoice_id IN (SELECT id FROM invoices WHERE status='draft'))""",
                             (row["rate_n"], row["id"], start.isoformat(), end.isoformat()))
            if row["include"] and not row["existing"]:
                add_weekly_lessons(conn, term, row["id"], row["day"], row["time_t"], row["minutes_n"], row["rate_n"])
        for lesson in after:
            conn.execute("DELETE FROM lessons WHERE id=? AND invoice_id IS NULL", (lesson["id"],))
        for draft in conn.execute("SELECT id FROM invoices WHERE status IN ('draft', 'revising')").fetchall():
            B.refresh_total(conn, draft["id"])
        conn.execute("UPDATE terms SET started_at=COALESCE(started_at, ?) WHERE id=?", (datetime.now().strftime(DATETIME_FORMAT), term["id"]))
        conn.commit()
        conn.close()
        done = [f"{plan['new_lessons']} lessons added"]
        if plan["already"]:
            done.append(f"{len(plan['already'])} students’ lessons already entered kept")
        if after:
            done.append(f"{len(after)} lessons after the last day deleted")
        flash(f"{name} is set up: " + ", ".join(done) + ".", "success")
        return redirect(url_for("register_bp.register", term=term["id"], week=1))
    conn.close()
    return render_template("start_term.html", term=term, name=name, start=start, end=end, weeks=(end - T.monday_of(start)).days // 7 + 1,
                           holiday_rows=holiday_rows, rows=rows, plan=plan, problems=problems, previewed=action == "preview",
                           drop_after=f is not None and f.get("drop_after") == "1", day_names=DAY_NAMES, fmt_long=fmt_long)
