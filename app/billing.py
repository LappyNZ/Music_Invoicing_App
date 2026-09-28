"""Invoices made from the register, kept line by line, and what happens to them after sending."""
import json
from datetime import date, datetime

import terms as T
from utils import (DATETIME_FORMAT, fmt_clock, fmt_day, invoice_number_of, lesson_cents, money,
                   new_invoice_number, parse_datetime)

CHARGED = ("taught", "missed")
CLOSED = ("carried", "written_off", "void")


def now():
    return datetime.now().strftime(DATETIME_FORMAT)


def log(conn, invoice_id, text):
    conn.execute("INSERT INTO invoice_events (invoice_id, at, text) VALUES (?, ?, ?)", (invoice_id, now(), text))


def get_invoice(conn, invoice_id):
    return conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()


def is_legacy(inv) -> bool:
    """Made before invoices were kept line by line: only its total is known."""
    return inv["term_id"] is None


# ---------------------------------------------------------------- lines

def lesson_line(lesson, prefix=""):
    when = lesson["when"] if "when" in lesson.keys() else parse_datetime(lesson["lesson_time"])
    if when is None or lesson["status"] == "holiday":
        return None
    minutes, charged = lesson["duration"], lesson["status"] in CHARGED
    kind = {"missed": "missed", "cancelled": "cancelled"}.get(lesson["status"], "extra" if lesson["kind"] == "extra" else "lesson")
    text = {
        "lesson": f"Lesson, {fmt_day(when)}, {fmt_clock(when)} ({minutes} min)",
        "extra": f"Extra lesson, {fmt_day(when)}, {fmt_clock(when)} ({minutes} min)",
        "missed": f"Missed lesson, {fmt_day(when)}, {fmt_clock(when)} ({minutes} min)",
        "cancelled": f"Cancelled, {fmt_day(when)}",
    }[kind]
    if lesson["note"] and kind in ("extra", "lesson"):
        text += f", {lesson['note']}"
    return {"key": f"L{lesson['id']}", "kind": kind, "lesson_id": lesson["id"], "date": when.date().isoformat(),
            "text": prefix + text, "cents": lesson_cents(minutes, lesson["rate"]) if charged else 0}


def invoice_students(conn, inv):
    """Everyone the invoice is for: its own student, plus anyone whose lessons are on it (a family invoice)."""
    return conn.execute("""SELECT * FROM students WHERE id = ? OR id IN (SELECT student_id FROM lessons WHERE invoice_id = ?)
                           ORDER BY name""", (inv["student_id"], inv["id"])).fetchall()


def live_lines(conn, inv):
    """The invoice as it stands now: its lessons from the register, then its items."""
    names = {s["id"]: s["name"].split()[0] for s in invoice_students(conn, inv)}
    multi = len(names) > 1
    lines = []
    for lesson in conn.execute("SELECT * FROM lessons WHERE invoice_id=? ORDER BY lesson_time", (inv["id"],)).fetchall():
        line = lesson_line(lesson, f"{names.get(lesson['student_id'], '')}: " if multi else "")
        if line:
            lines.append(line)
    for item in conn.execute("SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY id", (inv["id"],)).fetchall():
        lines.append({"key": f"I{item['id']}", "kind": item["kind"], "item_id": item["id"], "text": item["description"],
                      "cents": item["amount_cents"], "carried_invoice_id": item["carried_invoice_id"]})
    return lines


def latest_version(conn, inv):
    return conn.execute("SELECT * FROM invoice_versions WHERE invoice_id=? ORDER BY revision DESC LIMIT 1", (inv["id"],)).fetchone()


def current_lines(conn, inv):
    if is_legacy(inv):
        return []
    if inv["status"] in ("draft", "revising"):
        return live_lines(conn, inv)
    version = latest_version(conn, inv)
    return json.loads(version["lines_json"]) if version else live_lines(conn, inv)


def total_cents(conn, inv) -> int:
    if is_legacy(inv):
        return round((inv["total"] or 0) * 100)
    return sum(line["cents"] for line in current_lines(conn, inv))


def paid_cents(conn, inv) -> int:
    return conn.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE invoice_id=?", (inv["id"],)).fetchone()[0]


def owing_cents(conn, inv) -> int:
    return total_cents(conn, inv) - paid_cents(conn, inv)


def state(conn, inv) -> str:
    """draft, revising, unpaid, part, paid, carried, written_off or void."""
    status = inv["status"] or "draft"
    if status in ("draft", "revising") + CLOSED:
        return status
    if status == "paid":
        return "paid"
    paid = paid_cents(conn, inv)
    if paid and paid >= total_cents(conn, inv):
        return "paid"
    return "part" if paid else "unpaid"


def is_open(conn, inv) -> bool:
    return state(conn, inv) in ("unpaid", "part")


def extras_cents(lines) -> int:
    """Extra lessons and added items (not lessons or amounts carried from earlier)."""
    return sum(line["cents"] for line in lines if line["kind"] in ("extra", "item"))


# ---------------------------------------------------------------- the register

LESSON_STATUSES = ("taught", "cancelled", "missed", "holiday")


def set_lesson_status(conn, lesson_id, status):
    lesson = conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    if not lesson or status not in LESSON_STATUSES:
        return None
    invoice_id = lesson["invoice_id"]
    if status in CHARGED and invoice_id == 0:
        invoice_id = None      # was "nothing to charge"; now it needs billing
    conn.execute("UPDATE lessons SET status=?, invoice_id=? WHERE id=?", (status, invoice_id, lesson_id))
    if invoice_id:
        refresh_total(conn, invoice_id)
    return conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()


# ---------------------------------------------------------------- making drafts

def unbilled_students(conn, term):
    """Students with a charged lesson in this term (or its holidays) that isn't on an invoice yet."""
    return conn.execute("""SELECT DISTINCT students.* FROM lessons JOIN students ON students.id = lessons.student_id
                            WHERE lessons.invoice_id IS NULL AND lessons.status IN ('taught', 'missed')
                              AND date(lessons.lesson_time) <= ? ORDER BY students.name""",
                        (T.register_end(conn, term).isoformat(),)).fetchall()


def already_billed_elsewhere(conn, term):
    """Lessons in this term that an older invoice's dates already covered, by student."""
    return conn.execute("""SELECT students.id AS student_id, students.name, invoices.id AS invoice_id, invoices.invoice_number,
                                  invoices.created_at, invoices.start_date, invoices.end_date, COUNT(*) AS lessons
                             FROM lessons JOIN students ON students.id = lessons.student_id
                             JOIN invoices ON invoices.id = lessons.invoice_id
                            WHERE invoices.term_id IS NULL AND date(lessons.lesson_time) BETWEEN ? AND ?
                            GROUP BY students.id, invoices.id ORDER BY students.name""",
                        (term["start_date"], T.register_end(conn, term).isoformat())).fetchall()


def release_to_term(conn, term, invoice_id):
    """Bill an older invoice's lessons in this term on this term's invoices instead."""
    conn.execute("""UPDATE lessons SET invoice_id=NULL WHERE invoice_id=? AND date(lesson_time) BETWEEN ? AND ?""",
                 (invoice_id, term["start_date"], T.register_end(conn, term).isoformat()))


def owing_from_before(conn, student_ids, term):
    """Invoices from earlier terms for these students with money still owing, that could go on this term's invoice."""
    if not student_ids:
        return []
    marks = ",".join("?" * len(student_ids))
    rows = conn.execute(f"""SELECT * FROM invoices WHERE student_id IN ({marks}) AND term_id IS NOT ?
                              AND (term_id IS NULL OR start_date < ?)
                              AND (status = 'sent' OR (status = 'carried' AND carried_to IS NULL)) ORDER BY id""",
                        (*student_ids, term["id"], term["start_date"])).fetchall()
    return [inv for inv in rows if owing_cents(conn, inv) > 0]


def carry_onto(conn, old, new):
    owing = owing_cents(conn, old)
    label = invoice_number_of(old)
    if old["term_id"]:
        label += f" ({T.get_term(conn, old['term_id'])['name']})"
    conn.execute("""INSERT INTO invoice_items (invoice_id, kind, description, amount_cents, carried_invoice_id, created_at)
                    VALUES (?, 'carried', ?, ?, ?, ?)""", (new["id"], f"Still owing from {label}", owing, old["id"], now()))
    conn.execute("UPDATE invoices SET status='carried', carried_to=? WHERE id=?", (new["id"], old["id"]))
    log(conn, old["id"], f"{money(owing)} still owing moved onto {new['invoice_number']}")


def new_invoice(conn, term, student, one_off=False):
    cur = conn.execute("""INSERT INTO invoices (student_id, term_id, start_date, end_date, total, total_cents, status, revision, one_off)
                          VALUES (?, ?, ?, ?, 0, 0, 'draft', 1, ?)""",
                       (student["id"], term["id"], term["start_date"], term["end_date"], 1 if one_off else 0))
    number = new_invoice_number(cur.lastrowid)
    conn.execute("UPDATE invoices SET invoice_number=? WHERE id=?", (number, cur.lastrowid))
    return get_invoice(conn, cur.lastrowid)


def make_drafts(conn, term, family=False, carry=False):
    """One draft per student (or per family: students sharing an email) with lessons still to bill."""
    students = unbilled_students(conn, term)
    groups = {}
    for s in students:
        key = (s["email"] or "").strip().lower() if family and s["email"] else f"#{s['id']}"
        groups.setdefault(key, []).append(s)
    made = []
    end = T.register_end(conn, term).isoformat()
    for group in sorted(groups.values(), key=lambda g: g[0]["name"].lower()):
        inv = new_invoice(conn, term, group[0])
        ids = [s["id"] for s in group]
        marks = ",".join("?" * len(ids))
        conn.execute(f"""UPDATE lessons SET invoice_id=? WHERE invoice_id IS NULL AND student_id IN ({marks})
                          AND date(lesson_time) <= ?""", (inv["id"], *ids, end))
        for old in owing_from_before(conn, ids, term):
            if carry or old["status"] == "carried":   # "move to next invoice" was chosen for it earlier
                carry_onto(conn, old, inv)
        log(conn, inv["id"], "Draft made from the register")
        refresh_total(conn, inv["id"])
        made.append(inv["id"])
    # Lessons with nothing to charge (cancelled, holidays) for students with no invoice are dealt with too.
    conn.execute("""UPDATE lessons SET invoice_id=0 WHERE invoice_id IS NULL AND status IN ('cancelled', 'holiday')
                     AND date(lesson_time) BETWEEN ? AND ?""", (term["start_date"], end))
    return made


def attach_new_lessons(conn, inv):
    """Put any lessons added to the register since the draft was made onto it."""
    if inv["status"] not in ("draft", "revising") or is_legacy(inv) or inv["one_off"]:
        return
    ids = [s["id"] for s in invoice_students(conn, inv)]
    marks = ",".join("?" * len(ids))
    term = T.get_term(conn, inv["term_id"])
    conn.execute(f"""UPDATE lessons SET invoice_id=? WHERE invoice_id IS NULL AND student_id IN ({marks})
                      AND status IN ('taught', 'missed', 'cancelled') AND date(lesson_time) <= ?""",
                 (inv["id"], *ids, T.register_end(conn, term).isoformat()))


def refresh_total(conn, invoice_id):
    inv = get_invoice(conn, invoice_id)
    cents = total_cents(conn, inv)
    conn.execute("UPDATE invoices SET total_cents=?, total=? WHERE id=?", (cents, cents / 100, invoice_id))


def new_one_off(conn, term, student):
    inv = new_invoice(conn, term, student, one_off=True)
    log(conn, inv["id"], "One-off invoice started")
    return inv


def add_item(conn, inv, description, cents):
    conn.execute("INSERT INTO invoice_items (invoice_id, kind, description, amount_cents, created_at) VALUES (?, 'item', ?, ?, ?)",
                 (inv["id"], description, cents, now()))
    log(conn, inv["id"], f"Added: {description} {money(cents)}")
    refresh_total(conn, inv["id"])


def remove_item(conn, inv, item_id):
    item = conn.execute("SELECT * FROM invoice_items WHERE id=? AND invoice_id=?", (item_id, inv["id"])).fetchone()
    if not item:
        return
    if item["kind"] == "carried" and item["carried_invoice_id"]:
        old = get_invoice(conn, item["carried_invoice_id"])
        if old:
            conn.execute("UPDATE invoices SET status='sent', carried_to=NULL WHERE id=?", (old["id"],))
            log(conn, old["id"], f"Taken off {inv['invoice_number']}, so it’s owing here again")
    conn.execute("DELETE FROM invoice_items WHERE id=?", (item_id,))
    log(conn, inv["id"], f"Removed: {item['description']}")
    refresh_total(conn, inv["id"])


def delete_draft(conn, inv):
    for line in live_lines(conn, inv):
        if line["kind"] == "carried":
            remove_item(conn, inv, line["item_id"])
    if is_legacy(inv):     # lessons from before the register began aren't billed on a term's invoice
        first = conn.execute("SELECT MIN(start_date) FROM terms").fetchone()[0]
        conn.execute("UPDATE lessons SET invoice_id=0 WHERE invoice_id=? AND date(lesson_time) < ?", (inv["id"], first or "9999"))
    conn.execute("UPDATE lessons SET invoice_id=NULL WHERE invoice_id=?", (inv["id"],))
    conn.execute("DELETE FROM invoices WHERE id=?", (inv["id"],))


# ---------------------------------------------------------------- sending and after

def record_sent(conn, inv, sent_to, pdf_filename, subject, body):
    """Keep the lines exactly as sent, and mark the invoice sent (or paid, if payments already cover it)."""
    lines = [] if is_legacy(inv) else live_lines(conn, inv)
    cents = total_cents(conn, inv) if is_legacy(inv) else sum(line["cents"] for line in lines)
    conn.execute("""INSERT OR REPLACE INTO invoice_versions (invoice_id, revision, sent_at, sent_to, total_cents, lines_json,
                        pdf_filename, email_subject, email_body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (inv["id"], inv["revision"], now(), sent_to, cents, json.dumps(lines), pdf_filename, subject, body))
    status = "paid" if cents > 0 and paid_cents(conn, inv) >= cents else "sent"
    conn.execute("""UPDATE invoices SET status=?, total_cents=?, total=?, pdf_filename=COALESCE(?, pdf_filename),
                        emailed_at=COALESCE(emailed_at, ?), emailed_to=COALESCE(?, emailed_to) WHERE id=?""",
                 (status, cents, cents / 100, pdf_filename, now() if sent_to else None, sent_to, inv["id"]))
    if sent_to:
        log(conn, inv["id"], (f"Corrected invoice (version {inv['revision']}) emailed to {sent_to}" if inv["revision"] > 1
                              else f"Emailed to {sent_to}"))
    else:
        log(conn, inv["id"], "Marked as sent (not emailed)")


def changes_since_sent(conn, inv):
    """What the register says now that differs from the invoice as sent."""
    if is_legacy(inv) or inv["status"] not in ("sent", "paid"):
        return []
    version = latest_version(conn, inv)
    if not version:
        return []
    was = {line["key"]: line for line in json.loads(version["lines_json"])}
    words = {"lesson": "a lesson", "extra": "an extra lesson", "missed": "missed but charged", "cancelled": "cancelled, no charge"}
    out = []
    for line in live_lines(conn, inv):
        old = was.pop(line["key"], None)
        if old is None:
            out.append(f"Added: {line['text']}")
        elif (old["kind"], old["cents"]) != (line["kind"], line["cents"]):
            when = fmt_day(date.fromisoformat(line["date"])) if line.get("date") else line["text"]
            out.append(f"{when} is now {words.get(line['kind'], line['kind'])} (was {words.get(old['kind'], old['kind'])})")
    out += [f"Removed: {old['text']}" for old in was.values()]
    if inv["one_off"]:
        return out
    # lessons added to the register for these students since, and not billed anywhere yet
    term = T.get_term(conn, inv["term_id"])
    ids = [s["id"] for s in invoice_students(conn, inv)]
    marks = ",".join("?" * len(ids))
    for lesson in conn.execute(f"""SELECT * FROM lessons WHERE invoice_id IS NULL AND student_id IN ({marks})
                                     AND status IN ('taught', 'missed') AND date(lesson_time) BETWEEN ? AND ?""",
                               (*ids, term["start_date"], T.register_end(conn, term).isoformat())).fetchall():
        line = lesson_line(lesson)
        if line:
            out.append(f"Not on it yet: {line['text']}")
    return out


def start_correction(conn, inv):
    conn.execute("UPDATE invoices SET status='revising', revision=revision+1 WHERE id=?", (inv["id"],))
    inv = get_invoice(conn, inv["id"])
    log(conn, inv["id"], f"Correction started (version {inv['revision']})")
    attach_new_lessons(conn, inv)
    refresh_total(conn, inv["id"])


def cancel_correction(conn, inv):
    """Back to the invoice as last sent: its items and lessons as they were then."""
    version = latest_version(conn, inv)
    if not version:
        return
    sent = json.loads(version["lines_json"])
    lesson_ids = {line["lesson_id"] for line in sent if line.get("lesson_id")}
    for lesson in conn.execute("SELECT id FROM lessons WHERE invoice_id=?", (inv["id"],)).fetchall():
        if lesson["id"] not in lesson_ids:
            conn.execute("UPDATE lessons SET invoice_id=NULL WHERE id=?", (lesson["id"],))
    for line in live_lines(conn, inv):   # amounts carried on during the correction go back where they came from
        if line["kind"] == "carried" and line.get("carried_invoice_id"):
            conn.execute("UPDATE invoices SET status='sent', carried_to=NULL WHERE id=?", (line["carried_invoice_id"],))
    conn.execute("DELETE FROM invoice_items WHERE invoice_id=?", (inv["id"],))
    for line in sent:
        if line["kind"] in ("item", "carried"):
            conn.execute("""INSERT INTO invoice_items (id, invoice_id, kind, description, amount_cents, carried_invoice_id, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""", (line.get("item_id"), inv["id"], line["kind"], line["text"], line["cents"],
                                                              line.get("carried_invoice_id"), now()))
            if line.get("carried_invoice_id"):
                conn.execute("UPDATE invoices SET status='carried', carried_to=? WHERE id=?", (inv["id"], line["carried_invoice_id"]))
    paid = paid_cents(conn, inv)
    conn.execute("UPDATE invoices SET status=?, revision=? WHERE id=?",
                 ("paid" if paid and paid >= version["total_cents"] else "sent", version["revision"], inv["id"]))
    log(conn, inv["id"], "Correction cancelled")
    refresh_total(conn, inv["id"])


def sync_paid_fields(conn, inv):
    """Keep the invoice's own paid columns in step, so an older version of the app shows the same."""
    last = conn.execute("SELECT * FROM payments WHERE invoice_id=? ORDER BY paid_on DESC, id DESC LIMIT 1", (inv["id"],)).fetchone()
    paid = paid_cents(conn, inv)
    conn.execute("UPDATE invoices SET paid_amount=?, paid_at=?, paid_ref=? WHERE id=?",
                 (paid / 100 if last else None, f"{last['paid_on']} 00:00" if last else None, last["reference"] if last else None, inv["id"]))
    inv = get_invoice(conn, inv["id"])
    if inv["status"] in ("sent", "paid"):
        total = total_cents(conn, inv)
        conn.execute("UPDATE invoices SET status=? WHERE id=?", ("paid" if paid and paid >= total else "sent", inv["id"]))


def add_payment(conn, inv, cents, paid_on, reference=""):
    conn.execute("INSERT INTO payments (invoice_id, paid_on, amount_cents, reference, created_at) VALUES (?, ?, ?, ?, ?)",
                 (inv["id"], paid_on, cents, reference or None, now()))
    log(conn, inv["id"], f"Payment of {money(cents)} recorded ({paid_on}{', ref ' + reference if reference else ''})")
    sync_paid_fields(conn, inv)


def delete_payment(conn, inv, payment_id):
    p = conn.execute("SELECT * FROM payments WHERE id=? AND invoice_id=?", (payment_id, inv["id"])).fetchone()
    if p:
        conn.execute("DELETE FROM payments WHERE id=?", (payment_id,))
        log(conn, inv["id"], f"Payment of {money(p['amount_cents'])} ({p['paid_on']}) removed")
        sync_paid_fields(conn, inv)


def open_draft_for(conn, inv):
    """A draft (not a correction) already made for this invoice's student, that an amount owing could go on."""
    return conn.execute("""SELECT * FROM invoices WHERE status='draft' AND term_id IS NOT NULL AND one_off = 0 AND id != ?
                             AND (student_id = ? OR id IN (SELECT invoice_id FROM lessons WHERE student_id = ?))
                           ORDER BY id DESC LIMIT 1""", (inv["id"], inv["student_id"], inv["student_id"])).fetchone()


def move_to_next(conn, inv):
    """What's still owing goes on the family's next invoice: the draft already made, or the next one made."""
    draft = open_draft_for(conn, inv)
    if draft:
        carry_onto(conn, inv, draft)
        refresh_total(conn, draft["id"])
        return draft
    conn.execute("UPDATE invoices SET status='carried', carried_to=NULL WHERE id=?", (inv["id"],))
    log(conn, inv["id"], f"{money(owing_cents(conn, inv))} still owing to go on the next invoice")
    return None


def write_off(conn, inv, reason):
    conn.execute("UPDATE invoices SET status='written_off', write_off_reason=? WHERE id=?", (reason or None, inv["id"]))
    log(conn, inv["id"], f"{money(owing_cents(conn, inv))} written off" + (f": {reason}" if reason else ""))


def void(conn, inv, reason):
    """Void a sent invoice: its lessons can then go on a new one, and amounts it carried are owing again."""
    for line in live_lines(conn, inv):
        if line["kind"] == "carried" and line.get("carried_invoice_id"):
            conn.execute("UPDATE invoices SET status='sent', carried_to=NULL WHERE id=? AND carried_to=?",
                         (line["carried_invoice_id"], inv["id"]))
    if not is_legacy(inv):
        conn.execute("UPDATE lessons SET invoice_id=NULL WHERE invoice_id=?", (inv["id"],))
    conn.execute("UPDATE invoices SET status='void', voided_at=?, void_reason=? WHERE id=?", (now(), reason or None, inv["id"]))
    log(conn, inv["id"], "Voided" + (f": {reason}" if reason else ""))


def undo_close(conn, inv):
    """Undo "move to next invoice", "write off" or "void". Returns a message if it can't be undone."""
    if inv["status"] == "carried" and inv["carried_to"]:
        target = get_invoice(conn, inv["carried_to"])
        if target and target["status"] not in ("draft", "revising"):
            return f"It’s already on {target['invoice_number']}, which has been sent."
        if target:
            item = conn.execute("SELECT id FROM invoice_items WHERE invoice_id=? AND carried_invoice_id=?", (target["id"], inv["id"])).fetchone()
            if item:
                conn.execute("DELETE FROM invoice_items WHERE id=?", (item["id"],))
                refresh_total(conn, target["id"])
    if inv["status"] == "void" and not is_legacy(inv):
        version = latest_version(conn, inv)
        for line in json.loads(version["lines_json"]) if version else []:
            if line.get("lesson_id"):
                conn.execute("UPDATE lessons SET invoice_id=? WHERE id=? AND invoice_id IS NULL", (inv["id"], line["lesson_id"]))
    back = "sent" if (latest_version(conn, inv) or is_legacy(inv)) else "draft"
    conn.execute("UPDATE invoices SET status=?, carried_to=NULL, write_off_reason=NULL, voided_at=NULL, void_reason=NULL WHERE id=?",
                 (back, inv["id"]))
    log(conn, inv["id"], "Undone")
    sync_paid_fields(conn, get_invoice(conn, inv["id"]))
    return None
