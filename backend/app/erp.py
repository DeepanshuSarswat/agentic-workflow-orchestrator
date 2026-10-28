"""Mock ERP: vendors, purchase orders, and the payment ledger.

Every call can fail with a TransientERPError (set FLAKY_RATE) to simulate a
real, unreliable downstream system. Reads retry with exponential backoff.
The payment write is idempotent, which is what makes retrying it safe.
"""
import random
import re
import sqlite3
import time

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from . import config, db

VENDORS = {
    "V001": {"id": "V001", "name": "Acme Supplies", "status": "active"},
    "V002": {"id": "V002", "name": "Globex Logistics", "status": "active"},
    "V003": {"id": "V003", "name": "Initech Hardware", "status": "blocked",
             "blocked_reason": "Failed vendor compliance review"},
}

PURCHASE_ORDERS = {
    "PO-1001": {"po_number": "PO-1001", "vendor_id": "V001", "amount": 12000.0, "status": "open"},
    "PO-1002": {"po_number": "PO-1002", "vendor_id": "V002", "amount": 80000.0, "status": "open"},
    "PO-1003": {"po_number": "PO-1003", "vendor_id": "V001", "amount": 5000.0, "status": "open"},
    "PO-1004": {"po_number": "PO-1004", "vendor_id": "V002", "amount": 3000.0, "status": "closed"},
}


class TransientERPError(Exception):
    """A failure worth retrying (timeout, 503). Anything else is a real bug and is not retried."""


def _maybe_fail() -> None:
    if random.random() < config.flaky_rate():
        raise TransientERPError("ERP timeout (simulated)")


erp_retry = retry(
    retry=retry_if_exception_type(TransientERPError),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=0.1, max=1.0),
    reraise=True,
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@erp_retry
def find_vendor(vendor_name: str) -> dict:
    _maybe_fail()
    for v in VENDORS.values():
        if _norm(v["name"]) == _norm(vendor_name):
            return {"found": True, **v}
    return {"found": False, "vendor_name": vendor_name}


@erp_retry
def match_po(po_number: str, vendor_id: str, amount: float) -> dict:
    _maybe_fail()
    po = PURCHASE_ORDERS.get(po_number.strip().upper())
    if not po:
        return {"found": False, "po_number": po_number, "matched": False, "issues": ["PO not found"]}
    issues = []
    if po["vendor_id"] != vendor_id:
        issues.append("PO belongs to a different vendor")
    if po["status"] != "open":
        issues.append(f"PO is {po['status']}")
    variance = (amount - po["amount"]) / po["amount"] * 100
    if abs(variance) > config.price_tolerance_pct():
        issues.append(f"Invoice differs from PO amount by {variance:+.1f}%")
    return {
        "found": True,
        "po_amount": po["amount"],
        "variance_pct": round(variance, 2),
        "matched": not issues,
        "issues": issues,
    }


@erp_retry
def check_duplicate(vendor_id: str, invoice_number: str) -> dict:
    _maybe_fail()
    with db.conn() as c:
        row = c.execute(
            "SELECT * FROM payments WHERE vendor_id=? AND invoice_number=?",
            (vendor_id, invoice_number.strip()),
        ).fetchone()
    if row:
        return {"duplicate": True, "paid_amount": row["amount"], "paid_by_run": row["run_id"]}
    return {"duplicate": False}


@erp_retry
def pay_invoice(vendor_id: str, invoice_number: str, amount: float, run_id: str) -> dict:
    """Idempotent payment keyed on (vendor_id, invoice_number).

    - first call: inserts the ledger row -> paid
    - same run calls again (node retried, run replayed): returns the original payment -> paid, replayed
    - a different run tries the same invoice: blocked, nobody is paid twice
    """
    _maybe_fail()
    invoice_number = invoice_number.strip()
    with db.conn() as c:
        try:
            c.execute(
                "INSERT INTO payments VALUES (?,?,?,?,?)",
                (vendor_id, invoice_number, amount, run_id, time.time()),
            )
            return {"status": "paid", "replayed": False, "amount": amount}
        except sqlite3.IntegrityError:
            row = c.execute(
                "SELECT * FROM payments WHERE vendor_id=? AND invoice_number=?",
                (vendor_id, invoice_number),
            ).fetchone()
    if row["run_id"] == run_id:
        return {"status": "paid", "replayed": True, "amount": row["amount"]}
    return {"status": "duplicate_blocked", "paid_by_run": row["run_id"]}
