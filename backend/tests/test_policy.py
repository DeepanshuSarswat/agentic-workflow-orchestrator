from app.policy import route_after_assessment

INV = {"po_number": "PO-1001", "total": 12000.0}
OK = {"decision": "approve", "risk": "low", "reasons": []}


def test_clean_invoice_auto_pays():
    assert route_after_assessment(INV, OK, 50000) == "pay"


def test_llm_reject_wins():
    assert route_after_assessment(INV, {**OK, "decision": "reject"}, 50000) == "reject"


def test_any_risk_goes_to_human():
    assert route_after_assessment(INV, {**OK, "risk": "medium"}, 50000) == "human_review"


def test_rules_override_a_confident_llm():
    assert route_after_assessment({**INV, "total": 80000.0}, OK, 50000) == "human_review"
    assert route_after_assessment({**INV, "po_number": None}, OK, 50000) == "human_review"
