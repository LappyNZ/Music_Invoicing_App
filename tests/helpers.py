"""Small helpers shared by the tests of the term workflow."""
from datetime import date


def weekly(lesson, student_id, weeks=10, start="2026-07-20", time="15:30", **kw):
    """A lesson each week from `start`, made with the `lesson` fixture."""
    first = date.fromisoformat(start)
    return [lesson(student_id, f"{date.fromordinal(first.toordinal() + 7 * w)} {time}", **kw) for w in range(weeks)]


def draft_for(db, student_id):
    return db.execute("SELECT * FROM invoices WHERE student_id=? AND status='draft'", (student_id,)).fetchone()


def page(client, url):
    return client.get(url).get_data(as_text=True)
