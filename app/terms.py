"""Terms and the register: which weeks a term has, and which lessons fall in them."""
from datetime import date, datetime, timedelta

from utils import DATETIME_FORMAT, parse_datetime

# The register also shows lessons in the holidays after a term (makeups, or leftovers from
# "Weeks Repeating"), up to the next term, or this long after the last term we know of.
HOLIDAY_WEEKS = 8

# Public holidays the Start term page offers to skip (the app can't know regional ones for sure).
KNOWN_HOLIDAYS = {
    "2026-10-26": "Labour Day",
    "2026-11-13": "Canterbury Anniversary (Show Day, Canterbury only)",
    "2027-02-08": "Waitangi Day (observed)",
    "2027-03-26": "Good Friday",
    "2027-03-29": "Easter Monday",
    "2027-04-26": "ANZAC Day (observed)",
    "2027-06-07": "King’s Birthday",
    "2027-06-25": "Matariki",
    "2027-10-25": "Labour Day",
    "2027-11-12": "Canterbury Anniversary (Show Day, Canterbury only)",
}


def day(text) -> date:
    return date.fromisoformat(str(text)[:10])


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def all_terms(conn):
    return conn.execute("SELECT * FROM terms ORDER BY start_date").fetchall()


def get_term(conn, term_id):
    return conn.execute("SELECT * FROM terms WHERE id=?", (term_id,)).fetchone()


def next_term(conn, term):
    return conn.execute("SELECT * FROM terms WHERE start_date > ? ORDER BY start_date LIMIT 1", (term["start_date"],)).fetchone()


def term_weeks(term) -> int:
    return (day(term["end_date"]) - monday_of(day(term["start_date"]))).days // 7 + 1


def week_start(term, week: int) -> date:
    return monday_of(day(term["start_date"])) + timedelta(weeks=week - 1)


def week_of(term, d: date) -> int:
    return (d - monday_of(day(term["start_date"]))).days // 7 + 1


def register_end(conn, term) -> date:
    """The last day whose lessons belong to this term: the day before the next term, or some weeks of holidays."""
    following = next_term(conn, term)
    if following:
        return day(following["start_date"]) - timedelta(days=1)
    return day(term["end_date"]) + timedelta(weeks=HOLIDAY_WEEKS)


def register_weeks(conn, term) -> int:
    """The term's weeks, plus any holiday weeks after it that have lessons."""
    last = conn.execute("SELECT MAX(date(lesson_time)) FROM lessons WHERE date(lesson_time) BETWEEN ? AND ?",
                        (term["start_date"], register_end(conn, term).isoformat())).fetchone()[0]
    weeks = term_weeks(term)
    return max(weeks, week_of(term, day(last))) if last else weeks


def current_term(conn, today: date):
    """The term on now; in the holidays, the one that just finished; before any term, the first."""
    terms = all_terms(conn)
    if not terms:
        return None
    started = [t for t in terms if day(t["start_date"]) <= today]
    return started[-1] if started else terms[0]


def upcoming_term(conn, today: date):
    return conn.execute("SELECT * FROM terms WHERE start_date > ? ORDER BY start_date LIMIT 1", (today.isoformat(),)).fetchone()


def holidays(conn, term) -> dict:
    return {r["date"]: r["name"] for r in conn.execute("SELECT date, name FROM term_holidays WHERE term_id=?", (term["id"],))}


def checked_weeks(conn, term) -> set:
    return {r[0] for r in conn.execute("SELECT week FROM register_checks WHERE term_id=?", (term["id"],))}


def set_week_checked(conn, term, week: int, checked: bool):
    if checked:
        conn.execute("INSERT OR IGNORE INTO register_checks (term_id, week, checked_at) VALUES (?, ?, ?)",
                     (term["id"], week, datetime.now().strftime(DATETIME_FORMAT)))
    else:
        conn.execute("DELETE FROM register_checks WHERE term_id=? AND week=?", (term["id"], week))


LESSON_QUERY = """
    SELECT lessons.*, students.name AS student_name, students.active AS student_active,
           invoices.invoice_number AS invoice_number, invoices.status AS invoice_status
      FROM lessons
      JOIN students ON students.id = lessons.student_id
      LEFT JOIN invoices ON invoices.id = lessons.invoice_id
"""


def lessons_between(conn, first: date, last: date):
    """Lessons from `first` to `last` inclusive, oldest first, each with its datetime as `when`."""
    rows = conn.execute(LESSON_QUERY + " WHERE date(lessons.lesson_time) BETWEEN ? AND ? ORDER BY lessons.lesson_time, students.name",
                        (first.isoformat(), last.isoformat())).fetchall()
    out = []
    for r in rows:
        lesson = dict(r)
        lesson["when"] = parse_datetime(r["lesson_time"])
        if lesson["when"]:
            out.append(lesson)
    return out


def week_lessons(conn, term, week: int):
    start = week_start(term, week)
    return lessons_between(conn, start, start + timedelta(days=6))


def term_lessons(conn, term):
    return lessons_between(conn, day(term["start_date"]), register_end(conn, term))


def suggest_next_term(conn):
    """Name and dates for the term after the last one we know of (NZ school terms are usually 10 weeks)."""
    terms = all_terms(conn)
    if not terms:
        today = date.today()
        start = monday_of(today) + timedelta(weeks=1)
        return f"Term {1 + (today.month - 1) // 3} {today.year}", start, start + timedelta(weeks=9, days=4)
    last = terms[-1]
    name = last["name"]
    try:
        number, year = int(name.split()[1]), int(name.split()[2])
    except (IndexError, ValueError):
        number, year = 0, day(last["end_date"]).year
    if number >= 4:
        number, year = 1, year + 1
        start = monday_of(date(year, 2, 7))       # term 1 starts in the first week of February
    else:
        number += 1
        start = monday_of(day(last["end_date"])) + timedelta(weeks=3)   # after a two-week break
    return f"Term {number} {year}", start, start + timedelta(weeks=9, days=4)


def add_term(conn, name, start: date, end: date):
    cur = conn.execute("INSERT INTO terms (name, start_date, end_date) VALUES (?, ?, ?)",
                       (name, start.isoformat(), end.isoformat()))
    return get_term(conn, cur.lastrowid)


def today() -> date:
    """Today's date; settings can pin it (TODAY=2026-09-28) for tests and demonstrations."""
    from flask import current_app, has_app_context
    pinned = current_app.config.get("TODAY") if has_app_context() else None
    return date.fromisoformat(pinned) if pinned else date.today()


def invoicing_term(conn, on: date):
    """The term whose invoices are due: the latest one that has finished, else the one on now."""
    ended = conn.execute("SELECT * FROM terms WHERE end_date < ? ORDER BY start_date DESC LIMIT 1", (on.isoformat(),)).fetchone()
    return ended or current_term(conn, on)


def valid_date(text) -> bool:
    try:
        date.fromisoformat(str(text))
        return True
    except ValueError:
        return False
