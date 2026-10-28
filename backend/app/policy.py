"""Deterministic policy over the LLM's judgement.

The LLM proposes a decision. These rules decide whether money can move
without a human. They can make the outcome stricter, never looser.
"""


def route_after_assessment(invoice: dict, assessment: dict, auto_approve_limit: float) -> str:
    if assessment["decision"] == "reject":
        return "reject"
    if assessment["decision"] == "review" or assessment["risk"] != "low":
        return "human_review"
    # Hard rules: even a confident "approve" goes to a human here.
    if not invoice.get("po_number"):
        return "human_review"
    if invoice["total"] > auto_approve_limit:
        return "human_review"
    return "pay"


def route_after_human(human: dict) -> str:
    return "pay" if human.get("approved") else "reject"
