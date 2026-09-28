from datetime import date

import pytest

import billing as B
import terms as T
from helpers import draft_for, weekly


# ---------------------------------------------------------------- terms

def test_term_weeks_and_the_holidays_after_it(db, term3, term4, student, lesson):
    assert T.term_weeks(term3) == 10
    assert T.register_end(db, term3) == date(2026, 10, 11)          # the day before Term 4
    assert T.register_weeks(db, term3) == 10
    lesson(student(), "2026-10-01 10:00")                            # a holiday makeup, in week 11
    assert T.register_weeks(db, term3) == 11
    assert T.current_term(db, date(2026, 9, 28))["name"] == "Term 3 2026"
    assert T.current_term(db, date(2026, 10, 12))["name"] == "Term 4 2026"
    assert T.suggest_next_term(db) == ("Term 1 2027", date(2027, 2, 1), date(2027, 4, 9))


# ---------------------------------------------------------------- lines and drafts

def test_invoice_lines_follow_the_register(db, term3, student, lesson):
    ben = student("Ben Brown")
    lesson(ben, "2026-07-21 16:00", 45, 65)
    lesson(ben, "2026-07-28 16:00", 45, 65, status="cancelled")
    lesson(ben, "2026-08-04 16:00", 45, 65, status="missed")
    lesson(ben, "2026-08-11 16:00", 45, 65, status="holiday")
    lesson(ben, "2026-08-14 10:00", 30, 65, kind="extra", note="makeup for 28 Jul")

    B.make_drafts(db, term3)
    lines = B.live_lines(db, draft_for(db, ben))

    assert [(l["kind"], l["cents"]) for l in lines] == [("lesson", 4875), ("cancelled", 0), ("missed", 4875), ("extra", 3250)]
    assert lines[0]["text"] == "Lesson, Tue 21 Jul, 4:00 pm (45 min)"
    assert lines[3]["text"] == "Extra lesson, Fri 14 Aug, 10:00 am (30 min), makeup for 28 Jul"
    assert B.total_cents(db, draft_for(db, ben)) == 13000


def test_drafts_are_made_for_students_with_lessons_to_bill(db, term3, student, lesson):
    alice, ben, cara = student("Alice Aroha"), student("Ben Brown"), student("Cara Chen")
    weekly(lesson, alice)
    lesson(ben, "2026-07-21 16:00", status="cancelled")               # nothing to charge
    lesson(cara, "2026-10-13 16:00")                                  # Term 4: not yet

    made = B.make_drafts(db, term3)

    assert len(made) == 1
    inv = draft_for(db, alice)
    assert inv["invoice_number"].startswith("INV26-") and inv["term_id"] == term3["id"]
    assert B.total_cents(db, inv) == 35000
    assert db.execute("SELECT invoice_id FROM lessons WHERE student_id=?", (ben,)).fetchone()[0] == 0   # dealt with
    assert db.execute("SELECT invoice_id FROM lessons WHERE student_id=?", (cara,)).fetchone()[0] is None
    assert B.make_drafts(db, term3) == []                              # nothing left to bill


def test_one_invoice_per_family_groups_students_sharing_an_email(db, term3, student, lesson):
    emma = student("Emma Brown", "tom@example.com", "Tom Brown")
    oliver = student("Oliver Brown", "Tom@Example.com ", "Tom Brown")
    lesson(emma, "2026-07-21 16:15")
    lesson(oliver, "2026-07-21 16:45")

    B.make_drafts(db, term3, family=True)

    inv = db.execute("SELECT * FROM invoices").fetchone()
    assert [s["name"] for s in B.invoice_students(db, inv)] == ["Emma Brown", "Oliver Brown"]
    assert [l["text"] for l in B.live_lines(db, inv)] == ["Emma: Lesson, Tue 21 Jul, 4:15 pm (30 min)",
                                                           "Oliver: Lesson, Tue 21 Jul, 4:45 pm (30 min)"]


def legacy_invoice(db, student_id, total=245, paid=0, status="sent"):
    cur = db.execute("""INSERT INTO invoices (student_id, start_date, end_date, total, status, invoice_number)
                        VALUES (?, '2026-04-20', '2026-07-03', ?, ?, 'INV-2026-0079')""", (student_id, total, status))
    if paid:
        db.execute("INSERT INTO payments (invoice_id, paid_on, amount_cents, created_at) VALUES (?, '2026-07-20', ?, 'x')",
                   (cur.lastrowid, paid * 100))
    db.commit()
    return cur.lastrowid


@pytest.mark.parametrize("carry, expected", [(False, 3500), (True, 3500 + 20000)])
def test_amounts_still_owing_are_carried_only_when_asked(db, term3, student, lesson, carry, expected):
    kiri = student("Kiri Tane")
    old = legacy_invoice(db, kiri, total=350, paid=150)
    lesson(kiri, "2026-07-23 16:15")

    B.make_drafts(db, term3, carry=carry)

    inv = draft_for(db, kiri)
    assert B.total_cents(db, inv) == expected
    assert B.state(db, B.get_invoice(db, old)) == ("carried" if carry else "part")
    if carry:
        assert B.live_lines(db, inv)[-1]["text"] == "Still owing from INV-2026-0079"
        B.remove_item(db, inv, B.live_lines(db, inv)[-1]["item_id"])     # taken off again
        assert B.state(db, B.get_invoice(db, old)) == "part"


def test_moved_to_next_invoice_goes_on_the_next_draft_without_asking(db, term3, student, lesson):
    kiri = student("Kiri Tane")
    old = legacy_invoice(db, kiri)
    B.move_to_next(db, B.get_invoice(db, old))
    lesson(kiri, "2026-07-23 16:15")

    B.make_drafts(db, term3, carry=False)

    assert B.total_cents(db, draft_for(db, kiri)) == 3500 + 24500
    assert B.get_invoice(db, old)["carried_to"] == draft_for(db, kiri)["id"]


def test_a_draft_picks_up_lessons_added_to_the_register_later(db, term3, student, lesson):
    alice = student()
    lesson(alice, "2026-07-20 15:30")
    B.make_drafts(db, term3)
    lesson(alice, "2026-09-25 16:00", kind="extra")

    B.attach_new_lessons(db, draft_for(db, alice))

    assert B.total_cents(db, draft_for(db, alice)) == 7000


def test_lessons_inside_an_older_invoices_dates_are_shown_and_can_be_released(db, term3, student, lesson):
    cara = student("Cara Chen")
    old = db.execute("""INSERT INTO invoices (student_id, start_date, end_date, total, status, invoice_number)
                        VALUES (?, '2026-05-04', '2026-12-18', 900, 'paid', 'INV-2026-0090')""", (cara,)).lastrowid
    lid = lesson(cara, "2026-07-22 17:00")
    db.execute("UPDATE lessons SET invoice_id=? WHERE id=?", (old, lid))

    assert [(r["name"], r["invoice_number"], r["lessons"]) for r in B.already_billed_elsewhere(db, term3)] == [("Cara Chen", "INV-2026-0090", 1)]
    B.release_to_term(db, term3, old)
    assert len(B.make_drafts(db, term3)) == 1


# ---------------------------------------------------------------- after sending

@pytest.fixture
def sent(db, term3, student, lesson):
    """Chloe's Term 3 invoice, sent: ten 30-minute lessons at $70/h."""
    chloe = student("Chloe Wu", parent="Lin Wu")
    ids = weekly(lesson, chloe)
    B.make_drafts(db, term3)
    inv = draft_for(db, chloe)
    B.record_sent(db, inv, "lin@example.com", "INV26-0001.pdf", "subject", "body")
    return B.get_invoice(db, inv["id"]), ids


def test_sending_keeps_the_invoice_as_sent(db, sent):
    inv, lesson_ids = sent
    assert (inv["status"], inv["total_cents"], inv["emailed_to"]) == ("sent", 35000, "lin@example.com")
    assert B.state(db, inv) == "unpaid"
    B.set_lesson_status(db, lesson_ids[-1], "cancelled")           # the register changes later
    assert B.total_cents(db, inv) == 35000                          # the sent invoice doesn't
    assert B.changes_since_sent(db, inv) == ["Mon 21 Sep is now cancelled, no charge (was a lesson)"]


def test_correct_and_resend(db, sent):
    inv, lesson_ids = sent
    B.set_lesson_status(db, lesson_ids[-1], "cancelled")

    B.start_correction(db, inv)
    inv = B.get_invoice(db, inv["id"])
    assert (inv["status"], inv["revision"], B.total_cents(db, inv)) == ("revising", 2, 31500)
    B.record_sent(db, inv, "lin@example.com", "INV26-0001-v2.pdf", "s", "b")

    inv = B.get_invoice(db, inv["id"])
    assert (inv["status"], inv["revision"], inv["total_cents"]) == ("sent", 2, 31500)
    assert db.execute("SELECT COUNT(*) FROM invoice_versions WHERE invoice_id=?", (inv["id"],)).fetchone()[0] == 2
    assert B.changes_since_sent(db, inv) == []


def test_cancelling_a_correction_puts_it_back_as_sent(db, sent):
    inv, _ = sent
    B.start_correction(db, inv)
    inv = B.get_invoice(db, inv["id"])
    B.add_item(db, inv, "Exam entry", 12000)

    B.cancel_correction(db, inv)

    inv = B.get_invoice(db, inv["id"])
    assert (inv["status"], inv["revision"], B.total_cents(db, inv)) == ("sent", 1, 35000)
    assert db.execute("SELECT COUNT(*) FROM invoice_items WHERE invoice_id=?", (inv["id"],)).fetchone()[0] == 0


def test_part_and_full_payments(db, sent):
    inv, _ = sent
    B.add_payment(db, inv, 20000, "2026-10-02", "WU")
    inv = B.get_invoice(db, inv["id"])
    assert (B.state(db, inv), B.owing_cents(db, inv), inv["paid_amount"], inv["paid_at"]) == ("part", 15000, 200.0, "2026-10-02 00:00")

    B.add_payment(db, inv, 15000, "2026-10-09")
    inv = B.get_invoice(db, inv["id"])
    assert (inv["status"], B.state(db, inv)) == ("paid", "paid")

    B.delete_payment(db, inv, db.execute("SELECT MAX(id) FROM payments").fetchone()[0])
    assert B.state(db, B.get_invoice(db, inv["id"])) == "part"


@pytest.mark.parametrize("close", ["move", "write_off", "void"])
def test_closing_an_invoice_can_be_undone(db, sent, close):
    inv, _ = sent
    {"move": lambda: B.move_to_next(db, inv), "write_off": lambda: B.write_off(db, inv, "Moved away"),
     "void": lambda: B.void(db, inv, "Wrong family")}[close]()
    closed = B.get_invoice(db, inv["id"])
    assert B.state(db, closed) == {"move": "carried", "write_off": "written_off", "void": "void"}[close]
    if close == "void":
        assert db.execute("SELECT COUNT(*) FROM lessons WHERE invoice_id=?", (inv["id"],)).fetchone()[0] == 0

    assert B.undo_close(db, closed) is None

    back = B.get_invoice(db, inv["id"])
    assert B.state(db, back) == "unpaid"
    assert db.execute("SELECT COUNT(*) FROM lessons WHERE invoice_id=?", (inv["id"],)).fetchone()[0] == 10


def test_a_cancelled_lesson_that_becomes_charged_is_billed(db, term3, student, lesson):
    ben = student("Ben Brown")
    lid = lesson(ben, "2026-07-21 16:00", status="cancelled")
    B.make_drafts(db, term3)                                         # nothing to charge: marked dealt with

    B.set_lesson_status(db, lid, "missed")

    assert [inv for inv in [draft_for(db, ben)] if inv] == []
    assert len(B.make_drafts(db, term3)) == 1


def test_deleting_a_draft_frees_its_lessons_and_carried_amounts(db, term3, student, lesson):
    kiri = student("Kiri Tane")
    old = legacy_invoice(db, kiri)
    lesson(kiri, "2026-07-23 16:15")
    B.make_drafts(db, term3, carry=True)

    B.delete_draft(db, draft_for(db, kiri))

    assert db.execute("SELECT invoice_id FROM lessons WHERE student_id=?", (kiri,)).fetchone()[0] is None
    assert B.state(db, B.get_invoice(db, old)) == "unpaid"
