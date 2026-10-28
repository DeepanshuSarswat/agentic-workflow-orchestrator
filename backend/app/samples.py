"""Sample invoices for the UI dropdown. The eval dataset covers more cases."""

SAMPLES = {
    "Clean - auto-pays": """INVOICE INV-901
From: Acme Supplies
Date: 2026-10-20
PO: PO-1001
Office chairs x 20 @ 600.00
TOTAL DUE: INR 12,000.00""",
    "Duplicate - rejected": """INVOICE INV-778
From: Acme Supplies
Date: 2026-10-21
PO: PO-1003
Printer toner x 10 @ 500.00
TOTAL DUE: INR 5,000.00""",
    "Large - needs approval": """INVOICE INV-5521
From: Globex Logistics
Date: 2026-10-22
PO: PO-1002
Freight, Mumbai to Bengaluru, October
TOTAL DUE: INR 80,000.00""",
    "Blocked vendor - rejected": """INVOICE IH-2201
From: Initech Hardware
Date: 2026-10-22
PO: PO-1001
Laptops x 2 @ 6,000.00
TOTAL DUE: INR 12,000.00""",
    "Price mismatch - needs approval": """INVOICE INV-903
From: Acme Supplies
Date: 2026-10-23
PO: PO-1001
Office chairs x 20 @ 925.00
TOTAL DUE: INR 18,500.00""",
}
