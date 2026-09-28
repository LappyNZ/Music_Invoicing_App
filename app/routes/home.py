from flask import Blueprint, render_template, url_for

import billing as B
import terms as T
from db import get_db
from routes.invoices import summary
from utils import fmt_dm, fmt_long, money

home_bp = Blueprint("home_bp", __name__)


def weeks_text(weeks):
    if len(weeks) == 1:
        return f"week {weeks[0]}"
    if weeks == list(range(weeks[0], weeks[-1] + 1)):
        return f"weeks {weeks[0]} to {weeks[-1]}"
    return "weeks " + ", ".join(map(str, weeks[:-1])) + f" and {weeks[-1]}"


@home_bp.route("/")
def home():
    conn = get_db()
    today = T.today()
    current, term = T.current_term(conn, today), T.invoicing_term(conn, today)
    upcoming = T.upcoming_term(conn, today)
    ctx = {"today": today, "fmt_long": fmt_long, "money": money, "term": term, "current": current, "upcoming": upcoming}
    if not term:
        conn.close()
        return render_template("home.html", title="Welcome", sub="Start by setting up a term.", step={
            "title": "Set up your first term", "text": "Choose the dates and each student’s regular lesson.",
            "url": url_for("register_bp.start_term"), "label": "Start a term"}, steps=[], waiting=[], owing=0, **ctx)

    in_term = T.day(term["start_date"]) <= today <= T.day(term["end_date"])
    ended = T.day(term["end_date"]) < today
    weeks = T.term_weeks(term)
    checked = T.checked_weeks(conn, term)
    past = [w for w in range(1, weeks + 1) if T.week_start(term, w) <= today]
    unchecked = [w for w in past if w not in checked]
    invoices = [i for i in conn.execute("SELECT * FROM invoices WHERE term_id=?", (term["id"],)).fetchall() if i["status"] != "void"]
    drafts = [i for i in invoices if i["status"] in ("draft", "revising")]
    settled = [i for i in invoices if B.state(conn, i) in ("paid", "carried", "written_off")]
    unbilled = B.unbilled_students(conn, term) if ended else []
    waiting = sorted((summary(conn, i) for i in conn.execute("SELECT * FROM invoices WHERE status='sent'").fetchall()
                      if B.is_open(conn, i)), key=lambda r: r["sent"] or "")
    owing = sum(r["owing"] for r in waiting)
    next_up = upcoming if upcoming and not upcoming["started_at"] else None

    if unchecked and not invoices and (ended or len(unchecked) > 1):
        step = {"title": f"Check {weeks_text(unchecked)} in the register",
                "text": f"{len(checked)} of {weeks} weeks are checked. Go through the diary week by week and change only the lessons that were different.",
                "url": url_for("register_bp.register", term=term["id"], week=unchecked[0]), "label": f"Open week {unchecked[0]}"}
    elif ended and unbilled:
        step = {"title": f"Make the {term['name']} invoices",
                "text": f"{len(unbilled)} students have lessons to invoice. The drafts are made from the register in one go, and nothing is emailed until you say so.",
                "url": url_for("invoices_bp.make_invoices", term=term["id"]), "label": "Make invoices"}
    elif drafts:
        text = f"{money(sum(B.total_cents(conn, i) for i in drafts))} in total. Open any of them to add an item or read the email."
        if unchecked and (ended or len(unchecked) > 1):
            which = weeks_text(unchecked)
            text += f" {which[0].upper()}{which[1:]} {'isn’t' if len(unchecked) == 1 else 'aren’t'} checked in the register yet: the drafts update if you change it."
        step = {"title": f"Check and send {len(drafts)} invoice{'s' if len(drafts) != 1 else ''}", "text": text,
                "url": url_for("invoices_bp.invoice_list", term=term["id"]), "label": "Review invoices"}
    elif next_up:
        step = {"title": f"Get {next_up['name']} ready",
                "text": f"It starts {fmt_long(T.day(next_up['start_date']))}. Set the days off and check everyone’s regular lesson and rate; it takes a couple of minutes.",
                "url": url_for("register_bp.start_term", term=next_up["id"]), "label": f"Start {next_up['name']}"}
    elif waiting:
        step = {"title": f"Waiting for {len(waiting)} payment{'s' if len(waiting) != 1 else ''}",
                "text": f"{money(owing)} still to come. Record payments as they arrive.",
                "url": url_for("invoices_bp.invoice_list", show="unpaid"), "label": "See who hasn’t paid"}
    elif in_term:
        step = {"title": "Nothing to do right now", "text": "Check each week in the register as the term goes, or all at once at the end.",
                "url": url_for("register_bp.register", term=term["id"]), "label": "Open the register"}
    else:
        step = {"title": "All done for now", "text": "Everything is sent and paid.", "url": None, "label": ""}

    if in_term:
        title, sub = f"{term['name']} · week {T.week_of(term, today)} of {weeks}", f"It ends {fmt_long(T.day(term['end_date']))}."
    elif ended:
        title = f"{term['name']} has finished"
        sub = f"It ended {fmt_long(T.day(term['end_date']))}." + (f" {upcoming['name']} starts {fmt_long(T.day(upcoming['start_date']))}." if upcoming else "")
    else:
        title, sub = f"{term['name']} starts {fmt_long(T.day(term['start_date']))}", ""

    steps = [
        {"name": "Register", "text": f"{len(checked)} of {weeks} weeks checked", "done": len(checked) >= weeks,
         "url": url_for("register_bp.register", term=term["id"], week=(unchecked or [1])[0])},
        {"name": "Invoices", "text": f"{len(invoices)} made" if invoices else "Not made yet", "done": bool(invoices) and not unbilled,
         "url": url_for("invoices_bp.invoice_list", term=term["id"])},
        {"name": "Sent", "text": f"{len(invoices) - len(drafts)} of {len(invoices)} sent" if invoices else "Nothing to send yet",
         "done": bool(invoices) and not drafts, "url": url_for("invoices_bp.invoice_list", term=term["id"])},
        {"name": "Paid", "text": f"{len(settled)} of {len(invoices)} settled" if invoices else "Nothing owing yet",
         "done": bool(invoices) and len(settled) == len(invoices), "url": url_for("invoices_bp.invoice_list", show="unpaid")},
    ]
    conn.close()
    return render_template("home.html", title=title, sub=sub, step=step, steps=steps, waiting=waiting[:8], waiting_count=len(waiting),
                           owing=owing, next_up=next_up, fmt_dm=fmt_dm, **ctx)
