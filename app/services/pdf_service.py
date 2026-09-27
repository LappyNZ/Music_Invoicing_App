import os
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet


def build_invoice_pdf(
    filepath: str,
    logo_path: str,
    sender_email: str,
    sender_name: str,
    business_address_line1: str,
    business_address_line2: str,
    business_phone: str,
    business_mobile: str,
    bank_account: str,
    student_name: str,
    student_email: str,
    invoice_number: str,
    start_date_str: str,
    end_date_str: str,
    lessons: list,
    extras: list,
    total: float,
    fmt_date,
):
    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=60,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()
    elements = []

    # Paragraphs read their text as markup, so "<" or "&" in a name would vanish or break the PDF.
    def text(value):
        return Paragraph(escape(str(value or "")), styles["Normal"])

    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=80, height=80))
    elements.append(Spacer(1, 20))

    elements.append(text(business_address_line1))
    elements.append(text(business_address_line2))
    elements.append(text(f"Email: {sender_email}"))
    elements.append(text(f"Phone: {business_phone}"))
    elements.append(text(f"Mobile: {business_mobile}"))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(f"<b>Invoice No:</b> {escape(invoice_number)}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Date Issued:</b> {datetime.now().strftime('%d %b %Y')}", styles["Normal"]))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("<b>Invoice To:</b>", styles["Heading4"]))
    elements.append(text(f"Student: {student_name}"))
    elements.append(text(f"Email: {student_email}"))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(
        f"<b>Period:</b> {fmt_date(start_date_str)} to {fmt_date(end_date_str)}",
        styles["Normal"]
    ))
    elements.append(Spacer(1, 20))

    data = [["Date", "Duration (min)", "Rate ($/hr)", "Subtotal ($)"]]
    for l in lessons:
        data.append([l["date_str"], str(l["duration"]), f"{l['rate']:.2f}", f"{l['subtotal']:.2f}"])

    extra_rows = []
    if extras:
        data.append(["", "", "", ""])
        data.append([Paragraph("<b>Extra Items</b>", styles["Normal"]), "", "", ""])
        for e in extras:
            extra_rows.append(len(data))
            data.append([text(e["desc"]), "", "", f"{e['price']:.2f}"])

    right = ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)  # lines up with the subtotals
    data.append(["", "", Paragraph("<b>Total</b>", styles["Normal"]), Paragraph(f"<b>{total:.2f}</b>", right)])

    table = Table(data, colWidths=[150, 100, 100, 100])
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.5, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.black),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        # A long description wraps across the first three columns instead of running into the price.
        *[("SPAN", (0, row), (2, row)) for row in extra_rows],
    ]))
    elements.append(table)

    elements.append(Spacer(1, 40))
    elements.append(Paragraph("<b>Payment Information</b>", styles["Heading4"]))
    elements.append(Paragraph("Please pay to:", styles["Normal"]))
    elements.append(text(bank_account))
    elements.append(text(f"Reference: {invoice_number}"))
    elements.append(text(f"Particulars: {student_name}"))

    doc.build(elements)
