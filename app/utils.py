from datetime import datetime


def build_invoice_filename(created_at_str: str, invoice_id: int) -> str:
    year = created_at_str[:4] if created_at_str else str(datetime.now().year)
    return f"INV-{year}-{invoice_id:04d}.pdf"


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