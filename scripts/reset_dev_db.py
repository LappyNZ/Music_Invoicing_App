"""Start the development database again, filled with made-up students, a term's register and its invoices.

    python scripts/reset_dev_db.py            # data-dev/, as used by docker/docker-compose.dev.yml
    python scripts/reset_dev_db.py some/dir   # somewhere else

It deletes the database and invoice PDFs in that folder, then adds the sample data through the app
itself, so the database always has the app's current structure. Never point it at real data.

The sample is Term 3 2026, finished: every week checked, the invoices made (one per family), two sent
and one of those paid, the rest still drafts. Term 4 hasn't been started, so Home offers to get it ready.
"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Made-up people. Chloe and Leo are one family; Daniel's family pays less; Finn stopped after
# six weeks and is archived.
STUDENTS = [
    # name, email, parent, phone, school, day (1 = Monday), time, minutes, rate per hour
    ("Aroha Ngata", "ngata.whanau@example.com", "Mere Ngata", "021 555 0101", "Burnside High", 1, "15:30", 30, 70),
    ("Ben Carter", "ben.carter@example.com", "", "021 555 0102", "Cashmere High", 2, "16:00", 45, 70),
    ("Chloe Wu", "wu.family@example.com", "Lin Wu", "021 555 0103", "Burnside High", 3, "15:00", 30, 70),
    ("Leo Wu", "wu.family@example.com", "Lin Wu", "021 555 0103", "Burnside High", 3, "15:30", 30, 70),
    ("Daniel Smith", "kate.smith@example.com", "Kate Smith", "", "", 4, "16:30", 60, 60),
    ("Emma Brown", "tom.brown@example.com", "Tom Brown", "021 555 0105", "Christchurch Girls' High", 5, "15:30", 45, 70),
    ("Finn Taylor", "finn.taylor@example.com", "Sam Taylor", "", "Cashmere High", 1, "16:00", 30, 70),
]
TERM = {"name": "Term 3 2026", "start": "2026-07-20", "end": "2026-09-25", "weeks": 10}


def main(argv):
    data = Path(argv[0]) if argv else ROOT / "data-dev"
    db_path, pdf_dir = data / "music_school_dev.db", data / "invoices_pdfs"
    for leftover in (db_path, Path(f"{db_path}-journal")):
        leftover.unlink(missing_ok=True)
    shutil.rmtree(pdf_dir, ignore_errors=True)

    # The app reads these when it's imported, and creates the empty database (with Terms 3 and 4 2026).
    os.environ.update(APP_ENV="development", DB_PATH=str(db_path.absolute()),
                      INVOICE_PDF_DIR=str(pdf_dir.absolute()), EMAIL_ENABLED="0")
    sys.path.insert(0, str(ROOT / "app"))
    from app import app

    client = app.test_client()
    db = sqlite3.connect(db_path)

    def post(url, **form):
        response = client.post(url, data=form)
        if response.status_code not in (200, 302):
            sys.exit(f"{url} failed with {response.status_code}")

    def lesson_id(student_id, date):
        return db.execute("SELECT id FROM lessons WHERE student_id=? AND date(lesson_time)=?", (student_id, date)).fetchone()[0]

    term_id = db.execute("SELECT id FROM terms WHERE name=?", (TERM["name"],)).fetchone()[0]
    start = {"term": term_id, "name": TERM["name"], "start": TERM["start"], "end": TERM["end"], "action": "start",
             "extra_date_0": "2026-08-21", "extra_name_0": "Teacher away"}
    for student_id, (name, email, parent, phone, school, day, time, minutes, rate) in enumerate(STUDENTS, start=1):
        post("/students", name=name, email=email, parent=parent, phone=phone, school=school,
             lesson_day=day, lesson_start=time, lesson_minutes=minutes, lesson_rate=rate)
        start.update({f"day_{student_id}": day, f"time_{student_id}": time, f"minutes_{student_id}": minutes,
                      f"rate_{student_id}": rate, f"include_{student_id}": "1"})
    post("/terms/start", **start)

    # How the term went, as marked in the register
    post(f"/register/lesson/{lesson_id(1, '2026-08-03')}/status", status="cancelled")      # Aroha, week 3
    post(f"/register/lesson/{lesson_id(5, '2026-08-20')}/status", status="missed")         # Daniel, week 5
    post("/register/extra", student_id=6, date="2026-08-27", time="10:00", minutes=45, note="makeup for 21 Aug")
    finn = len(STUDENTS)
    for (later,) in db.execute("SELECT id FROM lessons WHERE student_id=? AND date(lesson_time) > '2026-08-28'", (finn,)).fetchall():
        post(f"/register/lesson/{later}/delete")
    for week in range(1, TERM["weeks"] + 1):
        post("/register/week", term=term_id, week=week, checked="1")

    # The invoices: one per family, two handed over (one paid), the rest still drafts
    post("/invoices/make", term=term_id, family="1")
    invoices = db.execute("SELECT id, total_cents FROM invoices ORDER BY id").fetchall()
    for invoice_id, total in (invoices[0], invoices[-1]):
        post(f"/invoices/{invoice_id}/mark-sent")
    post(f"/invoices/{invoices[0][0]}/payments", amount=f"{invoices[0][1] / 100:.2f}", paid_on="2026-10-02", reference="NGATA")
    post(f"/students/archive/{finn}")
    db.close()

    print(f"Development database ready: {db_path} ({len(STUDENTS)} students, {len(invoices)} invoices for {TERM['name']}). "
          "All names and details are made up.")


if __name__ == "__main__":
    main(sys.argv[1:])
