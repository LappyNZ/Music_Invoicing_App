"""Start the development database again, filled with made-up students, lessons and invoices.

    python scripts/reset_dev_db.py            # data-dev/, as used by docker/docker-compose.dev.yml
    python scripts/reset_dev_db.py some/dir   # somewhere else

It deletes the database and invoice PDFs in that folder, then adds the sample data through the app
itself, so the database always has the app's current structure. Never point it at real data.
"""
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Made-up people. The last one stopped lessons partway through the term and is archived.
STUDENTS = [
    # name, email, parent, phone, school, lesson minutes
    ("Aroha Ngata", "ngata.whanau@example.com", "Mere Ngata", "021 555 0101", "Burnside High", 30),
    ("Ben Carter", "ben.carter@example.com", "", "021 555 0102", "Cashmere High", 45),
    ("Chloe Wu", "wu.family@example.com", "Lin Wu", "021 555 0103", "Burnside High", 30),
    ("Daniel Smith", "kate.smith@example.com", "Kate Smith", "", "", 60),
    ("Emma Brown", "tom.brown@example.com", "Tom Brown", "021 555 0105", "Christchurch Girls' High", 45),
    ("Finn Taylor", "finn.taylor@example.com", "Sam Taylor", "", "Cashmere High", 30),
]
RATE = 70.0
WEEKS = 12


def main(argv):
    data = Path(argv[0]) if argv else ROOT / "data-dev"
    db_path, pdf_dir = data / "music_school_dev.db", data / "invoices_pdfs"
    for leftover in (db_path, Path(f"{db_path}-journal")):
        leftover.unlink(missing_ok=True)
    shutil.rmtree(pdf_dir, ignore_errors=True)

    # The app reads these when it's imported, and creates the empty database.
    os.environ.update(APP_ENV="development", DB_PATH=str(db_path.absolute()),
                      INVOICE_PDF_DIR=str(pdf_dir.absolute()), EMAIL_ENABLED="0")
    sys.path.insert(0, str(ROOT / "app"))
    from app import app

    client = app.test_client()

    def post(url, **form):
        response = client.post(url, data=form)
        if response.status_code not in (200, 302):
            sys.exit(f"{url} failed with {response.status_code}")

    today = date.today()
    term_start = today - timedelta(weeks=6, days=today.weekday())  # a Monday, six weeks ago
    first_half = (term_start.isoformat(), (term_start + timedelta(weeks=6, days=-1)).isoformat())

    for student_id, (name, email, parent, phone, school, minutes) in enumerate(STUDENTS, start=1):
        post("/students", name=name, email=email, parent=parent, phone=phone, school=school)
        day = term_start + timedelta(days=student_id % 5)
        weeks = 6 if student_id == len(STUDENTS) else WEEKS
        post("/lessons", student_id=student_id, lesson_time=f"{day}T{14 + student_id % 4}:30",
             duration=minutes, rate=RATE, repeat_weeks=weeks)

    # Invoices for the first half of the term: one paid, one sent, the rest still drafts.
    for student_id in (1, 2, 3, 6):
        post("/invoices", action="generate_pdf", student_id=student_id,
             start_date=first_half[0], end_date=first_half[1])
    post("/invoices/status/1", status="paid", paid_amount="210.00", paid_ref="NGATA")
    post("/invoices/status/2", status="sent")
    post(f"/students/archive/{len(STUDENTS)}")

    print(f"Development database ready: {db_path} ({len(STUDENTS)} students, 4 invoices). "
          "All names and details are made up.")


if __name__ == "__main__":
    main(sys.argv[1:])
