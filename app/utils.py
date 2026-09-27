from datetime import datetime, timezone


def new_invoice_number(invoice_id: int) -> str:
    # INV26-0042: 10 characters, so it fits the 12-character Reference field of a NZ bank payment.
    return f"INV{datetime.now():%y}-{invoice_id:04d}"


# Invoices store their number and PDF filename. Invoices made before that get them worked out
# the way they always were.
def invoice_number(created_at_str: str, invoice_id: int) -> str:
    year = created_at_str[:4] if created_at_str else str(datetime.now().year)
    return f"INV-{year}-{invoice_id:04d}"


def build_invoice_filename(created_at_str: str, invoice_id: int) -> str:
    return f"{invoice_number(created_at_str, invoice_id)}.pdf"


def invoice_number_of(inv) -> str:
    return inv["invoice_number"] or invoice_number(inv["created_at"], inv["id"])


def pdf_filename_of(inv) -> str:
    return inv["pdf_filename"] or build_invoice_filename(inv["created_at"], inv["id"])


DATETIME_FORMAT = "%Y-%m-%d %H:%M"  # how lesson times and payment dates are stored


def parse_datetime(text):
    """A date and time in any form the app has saved or been given one, or None if it can't be read."""
    for fmt in (DATETIME_FORMAT, "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%a, %d %b %y, %I:%M%p"):  # the last is how the app displays them
        try:
            return datetime.strptime((text or "").strip(), fmt)
        except ValueError:
            continue
    return None


def nz_school_term(date: datetime) -> str:
    if date.month <= 3:
        return "Term 1"
    elif date.month <= 6:
        return "Term 2"
    elif date.month <= 9:
        return "Term 3"
    else:
        return "Term 4"


def parse_date_any(s: str) -> datetime:
    if not s:
        return datetime.now()
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s[:19])
    except Exception:
        return datetime.now()


def fmt_date(s: str) -> str:
    return parse_date_any(s).strftime("%d-%m-%Y")


def utc_to_local(s: str) -> str:
    """created_at comes from SQLite's clock, which is UTC; show it in local time."""
    try:
        when = datetime.fromisoformat(s).replace(tzinfo=timezone.utc).astimezone()
    except (TypeError, ValueError):
        return s
    return when.strftime(DATETIME_FORMAT)