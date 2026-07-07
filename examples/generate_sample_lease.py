#!/usr/bin/env python3
"""Generate examples/sample_lease.pdf: a synthetic 2-page commercial lease
with invented parties and a plausible clause set (rent, term, use, utilities,
maintenance, insurance, indemnity, default, guaranty).

Everything in this file is invented. No real person, company, address, or
lease is referenced.

Usage:
    python examples/generate_sample_lease.py

Requires: reportlab==4.4.4 (pip install reportlab==4.4.4).
"""
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, PageBreak, SimpleDocTemplate, Spacer,
)


LANDLORD = "Northwood Real Estate Holdings LLC"
TENANT = "Sunbird Bakery Cafe Inc."
GUARANTOR = "Acme Guarantee Corp."

PAGE_ONE_CLAUSES = [
    ("<b>1. TERM.</b>",
     "The initial term of this Lease is thirty-six (36) months, commencing "
     "March 1, 2027 and expiring February 28, 2030. Tenant may exercise one "
     "renewal option of thirty-six (36) months by written notice to Landlord "
     "no later than ninety (90) days before expiration."),
    ("<b>2. RENT.</b>",
     "Tenant shall pay to Landlord monthly base rent of $8,500 on or before "
     "the first day of each calendar month. Late payments incur a fee of "
     "five percent (5%) of the unpaid balance."),
    ("<b>3. USE.</b>",
     "The Premises shall be used solely as a retail bakery and coffee shop, "
     "and for no other purpose without Landlord's prior written consent, "
     "which shall not be unreasonably withheld."),
    ("<b>4. UTILITIES.</b>",
     "Tenant is responsible for all electric, water, gas, and internet "
     "utilities serving the Premises. Landlord shall provide separately "
     "metered service where reasonably practicable."),
]

PAGE_TWO_CLAUSES = [
    ("<b>5. MAINTENANCE.</b>",
     "Landlord shall maintain the roof, exterior walls, foundation, and "
     "structural components of the Premises. Tenant shall maintain the "
     "interior in good and clean condition, including all fixtures and "
     "improvements installed by Tenant."),
    ("<b>6. INSURANCE.</b>",
     "Tenant shall maintain commercial general liability insurance of not "
     "less than $2,000,000 combined single limit and shall name Landlord as "
     "an additional insured. Certificates shall be delivered within ten "
     "(10) days of the Commencement Date."),
    ("<b>7. INDEMNITY.</b>",
     "Tenant shall indemnify and hold harmless Landlord from any claim "
     "arising out of Tenant's use of the Premises, except to the extent "
     "caused by Landlord's gross negligence or willful misconduct."),
    ("<b>8. DEFAULT.</b>",
     "A default occurs if Tenant fails to pay rent within ten (10) days of "
     "written notice, or if Tenant breaches any non-monetary covenant and "
     "fails to cure within thirty (30) days of notice."),
    ("<b>9. GUARANTY.</b>",
     "Guarantor unconditionally guarantees all obligations of Tenant under "
     "this Lease, up to a maximum of twenty-four (24) months of base rent."),
]


def build_document(output_path: Path) -> None:
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title="Sample Commercial Lease",
        author="synthetic (generated)",
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("<b>COMMERCIAL LEASE AGREEMENT</b>", styles["Title"]))
    story.append(Spacer(1, 0.25 * inch))
    story.append(Paragraph(
        f'This Lease is entered into by <b>{LANDLORD}</b> ("Landlord"), '
        f'<b>{TENANT}</b> ("Tenant"), and <b>{GUARANTOR}</b> ("Guarantor").',
        styles["BodyText"],
    ))
    story.append(Spacer(1, 0.25 * inch))
    for heading, body in PAGE_ONE_CLAUSES:
        story.append(Paragraph(heading, styles["BodyText"]))
        story.append(Paragraph(body, styles["BodyText"]))
        story.append(Spacer(1, 0.15 * inch))

    story.append(PageBreak())

    for heading, body in PAGE_TWO_CLAUSES:
        story.append(Paragraph(heading, styles["BodyText"]))
        story.append(Paragraph(body, styles["BodyText"]))
        story.append(Spacer(1, 0.15 * inch))
    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph(
        "IN WITNESS WHEREOF, the parties have executed this Lease as of "
        "the date first written above.",
        styles["BodyText"],
    ))

    doc.build(story)


if __name__ == "__main__":
    out = Path(__file__).parent / "sample_lease.pdf"
    build_document(out)
    print(f"wrote {out}")
