import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet


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

    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=80, height=80))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(business_address_line1, styles["Normal"]))
    elements.append(Paragraph(business_address_line2, styles["Normal"]))
    elements.append(Paragraph(f"Email: {sender_email}", styles["Normal"]))
    elements.append(Paragraph(f"Phone: {business_phone}", styles["Normal"]))
    elements.append(Paragraph(f"Mobile: {business_mobile}", styles["Normal"]))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(f"<b>Invoice No:</b> {invoice_number}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Date Issued:</b> {datetime.now().strftime('%d %b %Y')}", styles["Normal"]))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("<b>Invoice To:</b>", styles["Heading4"]))
    elements.append(Paragraph(f"Student: {student_name}", styles["Normal"]))
    elements.append(Paragraph(f"Email: {student_email}", styles["Normal"]))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(
        f"<b>Period:</b> {fmt_date(start_date_str)} to {fmt_date(end_date_str)}",
        styles["Normal"]
    ))
    elements.append(Spacer(1, 20))

    data = [["Date", "Duration (min)", "Rate ($/hr)", "Subtotal ($)"]]
    for l in lessons:
        data.append([l["date_str"], str(l["duration"]), f"{l['rate']:.2f}", f"{l['subtotal']:.2f}"])

    if extras:
        data.append(["", "", "", ""])
        data.append([Paragraph("<b>Extra Items</b>", styles["Normal"]), "", "", ""])
        for e in extras:
            data.append([e["desc"], "", "", f"{e['price']:.2f}"])

    data.append(["", "", Paragraph("<b>Total</b>", styles["Normal"]), Paragraph(f"<b>{total:.2f}</b>", styles["Normal"])])

    table = Table(data, colWidths=[150, 100, 100, 100])
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.5, colors.black),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, colors.black),
        ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.black),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ALIGN", (3, 1), (3, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    elements.append(table)

    elements.append(Spacer(1, 40))
    elements.append(Paragraph("<b>Payment Information</b>", styles["Heading4"]))
    elements.append(Paragraph("Please pay to:", styles["Normal"]))
    elements.append(Paragraph(bank_account, styles["Normal"]))
    elements.append(Paragraph(f"Reference: {student_name} + {invoice_number}", styles["Normal"]))

    doc.build(elements)