"""Structured outputs: the LLM must return these shapes, not free text."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    quantity: float
    unit_price: float


class Invoice(BaseModel):
    invoice_number: str = Field(description="Invoice number exactly as printed, e.g. INV-901")
    vendor_name: str = Field(description="Legal name of the vendor issuing the invoice")
    po_number: Optional[str] = Field(None, description="Purchase order number, or null if none is printed")
    invoice_date: Optional[str] = Field(None, description="ISO date if present")
    currency: str = Field("INR", description="ISO currency code")
    total: float = Field(description="Grand total payable")
    line_items: list[LineItem] = Field(default_factory=list)


class Assessment(BaseModel):
    decision: Literal["approve", "review", "reject"] = Field(
        description="approve = safe to pay, review = a human must look, reject = must not be paid"
    )
    risk: Literal["low", "medium", "high"]
    reasons: list[str] = Field(description="Short reasons, each grounded in a tool result")
