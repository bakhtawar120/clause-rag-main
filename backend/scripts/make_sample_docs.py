"""Generate the sample documents used for manual testing and for the evaluation golden set.

Run:  uv run python scripts/make_sample_docs.py
All content is fictional (Acme Inc.). The golden set in eval/golden_set.json depends on these facts,
so if you edit a fact here, update the matching question there.
"""

from __future__ import annotations

import csv
from pathlib import Path

from docx import Document as DocxDocument
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[1] / "sample_docs"


# --------------------------------------------------------------------------- PDF helper
def write_pdf(path: Path, title: str, pages: list[list[tuple[str, str]]], header: str) -> None:
    """pages = list of pages; each page = list of (kind, text) with kind in {"h1","h2","p"}."""
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(title)
    width, height = A4
    total = len(pages)
    for number, blocks in enumerate(pages, start=1):
        # running header and footer (the pre-processing step removes these)
        c.setFont("Helvetica", 8)
        c.drawString(2 * cm, height - 1.2 * cm, header)
        c.drawRightString(width - 2 * cm, 1.2 * cm, f"Page {number} of {total}")
        y = height - 2.6 * cm
        if number == 1:
            c.setFont("Helvetica-Bold", 18)
            c.drawString(2 * cm, y, title)
            y -= 1.1 * cm
        for kind, text in blocks:
            if kind == "h1":
                y -= 0.3 * cm
                c.setFont("Helvetica-Bold", 13)
                c.drawString(2 * cm, y, text)
                y -= 0.75 * cm
            elif kind == "h2":
                c.setFont("Helvetica-Bold", 11)
                c.drawString(2 * cm, y, text)
                y -= 0.6 * cm
            else:
                c.setFont("Helvetica", 10.5)
                for line in _wrap(text, 92):
                    c.drawString(2 * cm, y, line)
                    y -= 0.5 * cm
                y -= 0.25 * cm
        c.showPage()
    c.save()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


# --------------------------------------------------------------------------- 1. HR policy (PDF)
def hr_policy() -> None:
    pages = [
        [
            ("h1", "1. Purpose and scope"),
            ("p", "This policy explains how Acme Inc. manages working hours, leave, notice and remote work. "
                  "It applies to all permanent and fixed-term employees. It does not apply to contractors, "
                  "who are covered by their own service agreements."),
            ("h1", "2. Working hours"),
            ("p", "The standard working week is 40 hours, Monday to Friday, from 9:00 to 18:00 with a one-hour lunch break. "
                  "Overtime must be approved in advance by your line manager and is paid at 1.5 times the hourly rate."),
            ("h1", "3. Annual leave"),
            ("h2", "3.1 Entitlement"),
            ("p", "Every employee receives 20 working days of paid annual leave per calendar year, in addition to public holidays. "
                  "Leave is earned monthly, so new joiners receive a pro-rata share in their first year."),
            ("h2", "3.2 Carry over"),
            ("p", "Up to 5 unused days may be carried over to the next year. Carried-over days must be used by 31 March, "
                  "after which they are lost."),
        ],
        [
            ("h1", "4. Sick leave"),
            ("p", "Employees receive 10 days of paid sick leave per year. For absences longer than 3 consecutive days, "
                  "a medical certificate from a registered doctor is required."),
            ("h1", "5. Parental leave"),
            ("h2", "5.1 Maternity leave"),
            ("p", "Birth mothers are entitled to 16 weeks of fully paid maternity leave."),
            ("h2", "5.2 Paternity leave"),
            ("p", "Fathers and partners are entitled to 2 weeks of fully paid paternity leave, to be taken within "
                  "three months of the birth or adoption."),
            ("h1", "6. Notice"),
            ("h2", "6.1 Notice periods"),
            ("p", "Permanent employees must give and receive a minimum of thirty (30) days' notice in writing. "
                  "Longer periods may be agreed in individual contracts."),
            ("h2", "6.2 Probation"),
            ("p", "During probation, either side may end employment with one week's notice."),
        ],
        [
            ("h2", "6.3 Garden leave"),
            ("p", "The company may ask an employee to stay away from work during the notice period while remaining on full pay."),
            ("h2", "6.4 Payment in lieu of notice"),
            ("p", "Payment in lieu of notice may only be made with the written approval of the HR Director. "
                  "The approval must be kept on the employee's file."),
            ("h1", "7. Remote work"),
            ("p", "Employees may work remotely up to 2 days per week with their manager's approval. "
                  "Remote days cannot be carried over to the following week."),
            ("h1", "8. Policy owner"),
            ("p", "This policy is owned by the HR department and is reviewed every year. Version 7, effective 1 October 2026."),
        ],
    ]
    write_pdf(OUT / "HR_Policy_v7.pdf", "Acme Inc. Employee Handbook: HR Policy (v7)", pages,
              "Acme Inc. · HR Policy v7 · Internal")


# --------------------------------------------------------------------------- 2. Supplier agreement (PDF)
def supplier_agreement() -> None:
    pages = [
        [
            ("h1", "1. Parties"),
            ("p", "This Supply Agreement is made between Acme Inc. (the Buyer) and Northwind Components Ltd (the Supplier)."),
            ("h1", "2. Term"),
            ("p", "This Agreement starts on 1 March 2026 and continues for two (2) years unless terminated earlier under clause 14."),
            ("h1", "3. Payment"),
            ("h2", "3.1 Payment terms"),
            ("p", "The Buyer shall pay each undisputed invoice within forty-five (45) days of receiving it."),
            ("h2", "3.2 Late payment"),
            ("p", "Late payments carry interest of 1.5% per month on the overdue amount until paid in full."),
            ("h1", "4. Delivery"),
            ("p", "The Supplier shall deliver components to the Buyer's Lahore warehouse within ten (10) business days of each purchase order."),
        ],
        [
            ("h1", "12. Limitation of liability"),
            ("p", "Each party's total liability under this Agreement is limited to the fees paid by the Buyer in the twelve (12) months "
                  "before the claim arose."),
            ("h1", "14. Termination"),
            ("h2", "14.1 Termination for breach"),
            ("p", "Either party may terminate this Agreement immediately if the other party commits a material breach "
                  "and fails to remedy it within thirty (30) days of written notice."),
            ("h2", "14.2 Termination for convenience"),
            ("p", "Either party may terminate this Agreement for convenience by giving the other party not less than "
                  "sixty (60) days' written notice."),
            ("h1", "15. Governing law"),
            ("p", "This Agreement is governed by the laws of Pakistan, and the courts of Lahore have exclusive jurisdiction."),
        ],
    ]
    write_pdf(OUT / "Supplier_Agreement_2026.pdf", "Supply Agreement: Acme Inc. and Northwind Components Ltd", pages,
              "Acme Inc. · Supply Agreement 2026 · Confidential")


# --------------------------------------------------------------------------- 3. Employment contract (DOCX)
def employment_contract() -> None:
    doc = DocxDocument()
    doc.add_heading("Employment Contract Template", level=0)
    doc.add_paragraph("This contract is made between Acme Inc. (the Company) and [EMPLOYEE NAME] (the Employee).")
    sections = [
        ("1. Start date and probation",
         "Employment starts on [START DATE]. The first three (3) months are a probation period."),
        ("2. Working hours", "The Employee will work 40 hours per week in line with the HR Policy."),
        ("3. Salary", "The salary is [SALARY] per month, paid on the last working day of each month."),
        ("4. Annual leave", "The Employee is entitled to annual leave as set out in the HR Policy."),
        ("9. Notice",
         "Either party may end the employment by giving thirty (30) days' notice in writing. "
         "The Company may, at its discretion, make a payment in lieu of notice."),
        ("10. Confidentiality",
         "The Employee must keep Company information confidential during employment and for two (2) years after it ends."),
        ("11. Company property",
         "On leaving, the Employee must return all Company property, including laptops, phones and access cards."),
    ]
    for heading, text in sections:
        doc.add_heading(heading, level=1)
        doc.add_paragraph(text)
    doc.add_heading("Signatures", level=1)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "For the Company"
    table.cell(0, 1).text = "Employee"
    table.cell(1, 0).text = "HR Director"
    table.cell(1, 1).text = "[EMPLOYEE NAME]"
    doc.save(OUT / "Employment_Contract_Template.docx")


# --------------------------------------------------------------------------- 4. Returns & warranty FAQ (Markdown)
def returns_faq() -> None:
    (OUT / "Returns_and_Warranty_FAQ.md").write_text(
        """# Returns and Warranty FAQ

## How long do I have to return a product?
You can return a product within 7 days of delivery. It must be unused and in its original packaging.

## How do refunds work?
Refunds go back to your original payment method within 5 to 7 business days after we receive the return.

## Are sale items returnable?
Sale items are final sale and cannot be returned, unless they are faulty.

## Can I return opened earbuds?
For hygiene reasons, opened earbuds cannot be returned. Faulty earbuds are still covered by the warranty.

## What warranty do products have?
All products have a 1-year warranty that covers repair or replacement of manufacturing faults.

## Does the X200 have a longer warranty?
Yes. The X200 Wireless Headphones carry an extended 2-year warranty.

## What if my product breaks after the return window?
After the 7-day return window, a faulty product is handled as a warranty repair instead of a return.
""",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- 5. Price list (CSV)
def price_list() -> None:
    rows = [
        ["SKU", "Product", "Price (PKR)", "Warranty (months)", "In stock"],
        ["SKU-4471", "X200 Wireless Headphones", "24,999", "24", "Yes"],
        ["SKU-3302", "A50 Earbuds", "8,499", "12", "Yes"],
        ["SKU-5120", "S9 Pro Speaker", "32,000", "12", "No"],
        ["SKU-1108", "65W USB-C Charger", "3,999", "6", "Yes"],
        ["SKU-2210", "W3 Smart Watch", "19,500", "12", "Yes"],
        ["SKU-6605", "K1 Mechanical Keyboard", "14,250", "12", "Yes"],
        ["SKU-7781", "M2 Wireless Mouse", "4,800", "12", "Yes"],
    ]
    with (OUT / "Price_List_Q3_2026.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


# --------------------------------------------------------------------------- 6. Travel policy (HTML)
def travel_policy() -> None:
    (OUT / "Travel_and_Expenses_Policy.html").write_text(
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Travel and Expenses Policy</title></head>
<body>
<header>Acme Inc. intranet</header>
<h1>Travel and Expenses Policy</h1>
<h2>Daily allowance</h2>
<p>For domestic travel, the daily allowance is PKR 6,000 per day. For international travel, the daily allowance is USD 80 per day.</p>
<h2>Flights</h2>
<p>Book economy class for flights under 6 hours. Business class is allowed for flights over 6 hours with director approval.</p>
<h2>Personal car</h2>
<p>Using your personal car for work is reimbursed at PKR 45 per kilometre.</p>
<h2>Claims</h2>
<p>Submit expense claims within 30 days of the trip, with receipts for every item over PKR 1,000.</p>
<footer>Last updated September 2026</footer>
</body></html>
""",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- 7. Delivery policy (TXT)
def delivery_policy() -> None:
    (OUT / "Delivery_Policy.txt").write_text(
        """DELIVERY POLICY

Standard delivery
Standard delivery takes 3 to 5 business days anywhere in Pakistan.

Express delivery
Express delivery takes 1 business day and is available in Lahore, Karachi and Islamabad only.

Delivery charges
Delivery is free for orders over PKR 10,000. Smaller orders pay a flat fee of PKR 250.

Delivery days
We deliver Monday to Saturday. There are no deliveries on Sundays or public holidays.

Tracking
Every order gets a tracking link by SMS and email as soon as it leaves the warehouse.
""",
        encoding="utf-8",
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hr_policy()
    supplier_agreement()
    employment_contract()
    returns_faq()
    price_list()
    travel_policy()
    delivery_policy()
    for path in sorted(OUT.iterdir()):
        print(f"{path.name:40s} {path.stat().st_size:>8,d} bytes")


if __name__ == "__main__":
    main()
