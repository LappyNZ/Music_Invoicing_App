"""Bring back students who were deleted while they still had invoices.

Deleting a student used to leave their invoices without a name (the invoice list now shows them as
"Deleted student #7"). This finds those students in an old copy of the database and adds them back
as archived students, with their old id, so their invoices show under their names again. Their
lessons aren't brought back.

Run it inside the container, with the old copy somewhere the container can read (e.g. /data):

    docker exec music-invoice python -m tools.restore_deleted_students /data/restore-source.db
    docker exec music-invoice python -m tools.restore_deleted_students /data/restore-source.db --apply

Without --apply it only shows what it would do. A student is only brought back when the old copy also
has one of their invoices (same id, period and total), which shows it's the same person.
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from config import get_config
from utils import DATETIME_FORMAT, invoice_number_of


def open_read_only(path):
    conn = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def find_student(backups, student_id, invoices):
    """(backup name, student row, matching invoice) from the first backup that proves it, else what was found."""
    found = None
    for name, backup in backups:
        student = backup.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        if not student:
            continue
        for inv in invoices:
            match = backup.execute("""SELECT 1 FROM invoices WHERE id=? AND student_id=? AND start_date IS ?
                                        AND end_date IS ? AND ABS(total - ?) < 0.005""",
                                   (inv["id"], student_id, inv["start_date"], inv["end_date"], inv["total"] or 0)).fetchone()
            if match:
                return name, student, inv
        found = found or (name, student, None)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bring back deleted students who still have invoices, as archived students.")
    parser.add_argument("backups", nargs="+", help="old copies of the database to look in, in order")
    parser.add_argument("--apply", action="store_true", help="make the changes (without it, only show them)")
    parser.add_argument("--db", default=get_config().DB_PATH, help="the app's database (default: %(default)s)")
    args = parser.parse_args(argv)

    for path in [args.db, *args.backups]:
        if not os.path.isfile(path):
            print(f"Can't find {path}")
            return 1

    live = sqlite3.connect(args.db, timeout=30, isolation_level=None)
    live.row_factory = sqlite3.Row
    if "active" not in [r["name"] for r in live.execute("PRAGMA table_info(students)")]:
        print("This database hasn't been upgraded yet. Start the new version of the app first, then run this again.")
        return 1
    backups = [(os.path.basename(path), open_read_only(path)) for path in args.backups]

    live.execute("BEGIN IMMEDIATE")  # nothing else can change the database until we're done
    orphans = live.execute("""SELECT * FROM invoices
                               WHERE student_id IS NOT NULL AND student_id NOT IN (SELECT id FROM students)
                               ORDER BY student_id, id""").fetchall()
    by_student = {}
    for inv in orphans:
        by_student.setdefault(inv["student_id"], []).append(inv)
    print(f"{len(orphans)} invoice(s) belong to {len(by_student)} deleted student(s).")

    restored = 0
    archived_at = datetime.now().strftime(DATETIME_FORMAT)
    for student_id, invoices in by_student.items():
        numbers = ", ".join(invoice_number_of(inv) for inv in invoices)
        print(f"\nStudent #{student_id}, invoice(s) {numbers}:")
        found = find_student(backups, student_id, invoices)
        if not found:
            print("  not in any of the old copies, so left as it is.")
            continue
        source, student, proof = found
        details = ", ".join(str(student[c]) for c in ("parent", "email") if c in student.keys() and student[c])
        print(f"  {student['name']}" + (f" ({details})" if details else "") + f", from {source}.")
        if not proof:
            print("  None of their invoices are in that copy, so it may be a different person. Left as it is.")
            continue
        print(f"  Same person: {invoice_number_of(proof)} is in that copy too.")
        row = {c: student[c] for c in ("name", "email", "parent", "phone", "school") if c in student.keys()}
        row["email"] = row.get("email") or ""  # can't be empty in this database
        live.execute(f"INSERT INTO students (id, {', '.join(row)}, active, archived_at) "
                     f"VALUES (?, {', '.join('?' * len(row))}, 0, ?)",
                     (student_id, *row.values(), archived_at))
        restored += 1

    if args.apply:
        live.execute("COMMIT")
        print(f"\nDone: {restored} student(s) brought back as archived students.")
    else:
        live.execute("ROLLBACK")
        print(f"\nNothing has been changed. Run again with --apply to bring back {restored} student(s).")
    live.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
