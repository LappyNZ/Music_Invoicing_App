import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from utils import money

PLACEHOLDER_NAME = "Your Business Name"   # config.py's default, not a real name
GREY = colors.HexColor("#5B605A")


def build_invoice_pdf(target, *, logo_path, business, number, issued, bill_to, bill_to_email, for_names, period,
                      lines, total_cents, particulars, revised_note=""):
    """An invoice laid out from its lines. `target` is a file path or a file-like object.

    `business` holds name, address lines, phone, mobile, email and bank account; `lines` are the invoice's lines
    (text, kind and cents), exactly as they'll be charged. Cancelled lessons are left off.
    """
    doc = SimpleDocTemplate(target, pagesize=A4, leftMargin=42, rightMargin=42, topMargin=40, bottomMargin=40,
                            title=f"Invoice {number}", author=business.get("name") or "")
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14)
    small = ParagraphStyle("Small", parent=normal, fontSize=9, leading=12, textColor=GREY)
    label = ParagraphStyle("Label", parent=small, fontName="Helvetica-Bold", fontSize=8, leading=11)
    right = ParagraphStyle("Right", parent=normal, alignment=TA_RIGHT)
    title = ParagraphStyle("Title", parent=right, fontName="Helvetica-Bold", fontSize=20, leading=24)

    def para(text, style=normal):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)

    # Header: logo and who it's from on the left, "Invoice", number and date on the right
    contact = [business.get("address1"), business.get("address2"),
               " · ".join(x for x in (business.get("phone") and f"Phone {business['phone']}",
                                       business.get("mobile") and f"Mobile {business['mobile']}") if x),
               business.get("email")]
    from_block = []
    name = business.get("name")
    if name and name != PLACEHOLDER_NAME:
        from_block.append(Paragraph(f"<b>{escape(name)}</b>", normal))
    from_block.append(para("\n".join(x for x in contact if x), small))
    logo = Image(logo_path, width=78, height=78) if logo_path and os.path.exists(logo_path) else Spacer(78, 78)
    head = Table([[logo, from_block, [Paragraph("Invoice", title), para(number, right), para(issued, right)]]],
                 colWidths=[90, 245, 176])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    elements = [head, Spacer(1, 10)]
    if revised_note:
        elements.append(Paragraph(f"<b>{escape(revised_note)}</b>", ParagraphStyle("Revised", parent=normal, textColor=colors.HexColor("#8A4F00"))))
        elements.append(Spacer(1, 6))

    who = Table([[[para("BILL TO", label), para(f"{bill_to}\n{bill_to_email or ''}")],
                  [para("FOR", label), para(f"{for_names}\n{period}")]]], colWidths=[255, 256])
    who.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.black), ("TOPPADDING", (0, 0), (-1, -1), 8)]))
    elements += [who, Spacer(1, 14)]

    rows = [[para("DESCRIPTION", label), Paragraph("AMOUNT", ParagraphStyle("LabelR", parent=label, alignment=TA_RIGHT))]]
    for line in lines:
        if line["kind"] == "cancelled":     # no charge, so not on the invoice (the register still has it)
            continue
        rows.append([para(line["text"]), para(money(line["cents"]), right)])
    rows.append([Paragraph("<b>Total</b>", normal), Paragraph(f"<b>{money(total_cents)}</b>", right)])
    table = Table(rows, colWidths=[421, 90], repeatRows=1)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, colors.HexColor("#D5D8D2")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.black),
        ("TOPPADDING", (0, -1), (-1, -1), 6),
    ]))
    elements += [table, Spacer(1, 18)]

    pay = [Paragraph("<b>Prompt payment is appreciated.</b>", normal), Spacer(1, 4),
           para(f"Please pay to: {business.get('bank') or ''}"),
           Paragraph(f"Reference: <b>{escape(number)}</b>", normal),
           Paragraph(f"Particulars: <b>{escape(particulars)}</b>", normal)]
    box = Table([[pay]], colWidths=[511])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F3EF")),
                             ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 10),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
    elements.append(box)
    doc.build(elements)
