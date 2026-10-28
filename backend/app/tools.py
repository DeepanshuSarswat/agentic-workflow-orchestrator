"""Tools the agent can call. The docstrings are what the LLM reads to decide when to call them."""
from langchain_core.tools import tool

from . import erp


@tool
def lookup_vendor(vendor_name: str) -> dict:
    """Look up a vendor in the ERP by name. Returns the vendor id and status
    (active or blocked), or found=false if the vendor is not registered."""
    return erp.find_vendor(vendor_name)


@tool
def match_purchase_order(po_number: str, vendor_id: str, amount: float) -> dict:
    """Check an invoice against its purchase order: the PO must exist, belong to
    this vendor, be open, and its amount must be within tolerance of the invoice total."""
    return erp.match_po(po_number, vendor_id, amount)


@tool
def check_duplicate_invoice(vendor_id: str, invoice_number: str) -> dict:
    """Check the payment ledger for an invoice with this number already paid to this vendor."""
    return erp.check_duplicate(vendor_id, invoice_number)


TOOLS = [lookup_vendor, match_purchase_order, check_duplicate_invoice]
