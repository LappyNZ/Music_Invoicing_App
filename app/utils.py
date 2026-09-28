from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


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

# ---- Money and dates as the term workflow shows them ----
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]


def money(cents) -> str:
    """$1,234.50 (and −$20.00 for a discount)."""
    cents = int(cents or 0)
    return ("−$" if cents < 0 else "$") + f"{abs(cents) / 100:,.2f}"


def to_cents(text):
    """Cents from what someone typed ("1,200", "$45.5", "-20"), or None if it isn't a sensible amount."""
    cleaned = str(text or "").replace("$", "").replace(",", "").replace("−", "-").strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return int(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def lesson_cents(minutes, rate_per_hour) -> int:
    """What a lesson costs, rounded to the cent the way people round (half up)."""
    exact = Decimal(str(minutes)) * Decimal(str(rate_per_hour)) / 60
    return int(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def fmt_day(d) -> str:
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"          # Mon 20 Jul


def fmt_dm(d) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"                               # 20 Jul


def fmt_long(d) -> str:
    return f"{DAY_NAMES[d.weekday()]} {d.day} {MONTH_NAMES[d.month - 1]}"   # Monday 20 July


def fmt_full(d) -> str:
    return f"{d.day} {MONTH_NAMES[d.month - 1]} {d.year}"                 # 20 July 2026


def fmt_clock(t) -> str:
    """3:30 pm, from a time or datetime."""
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'pm' if t.hour >= 12 else 'am'}"
