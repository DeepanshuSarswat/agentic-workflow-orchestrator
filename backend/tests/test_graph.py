"""End-to-end graph runs with a scripted LLM: tool loop, interrupt, resume, idempotent pay."""
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph import build_graph

LARGE = {"invoice_number": "INV-5521", "vendor_name": "Globex Logistics", "po_number": "PO-1002", "total": 80000.0}
CALLS = [
    {"name": "lookup_vendor", "args": {"vendor_name": "Globex Logistics"}, "id": "c1"},
    {"name": "check_duplicate_invoice", "args": {"vendor_id": "V002", "invoice_number": "INV-5521"}, "id": "c2"},
    {"name": "match_purchase_order", "args": {"po_number": "PO-1002", "vendor_id": "V002", "amount": 80000.0}, "id": "c3"},
]
APPROVE = {"decision": "approve", "risk": "low", "reasons": ["vendor active", "PO matched"]}


def _run(graph, run_id, payload):
    cfg = {"configurable": {"thread_id": run_id}}
    for _ in graph.stream(payload, cfg):
        pass
    return graph.get_state(cfg)


def test_large_invoice_pauses_then_pays_after_approval(scripted_llm):
    graph = build_graph(llm=scripted_llm(LARGE, CALLS, APPROVE), checkpointer=InMemorySaver())

    state = _run(graph, "r1", {"run_id": "r1", "invoice_text": "..."})
    assert state.next == ("human_review",)                 # paused by policy (80k > 50k)
    tool_results = [m for m in state.values["messages"] if m.type == "tool"]
    assert len(tool_results) == 3                          # all three tools really ran

    state = _run(graph, "r1", Command(resume={"approved": True, "comment": "ok"}))
    assert state.next == ()
    assert state.values["outcome"] == "paid"


def test_rejection_by_human(scripted_llm):
    graph = build_graph(llm=scripted_llm(LARGE, CALLS, APPROVE), checkpointer=InMemorySaver())
    _run(graph, "r2", {"run_id": "r2", "invoice_text": "..."})
    state = _run(graph, "r2", Command(resume={"approved": False}))
    assert state.values["outcome"] == "rejected"


def test_second_run_for_same_invoice_cannot_pay(scripted_llm):
    small = {**LARGE, "total": 12000.0, "invoice_number": "INV-901", "vendor_name": "Acme Supplies", "po_number": "PO-1001"}
    graph = build_graph(llm=scripted_llm(small, CALLS, APPROVE), checkpointer=InMemorySaver())
    assert _run(graph, "a", {"run_id": "a", "invoice_text": "..."}).values["outcome"] == "paid"
    assert _run(graph, "b", {"run_id": "b", "invoice_text": "..."}).values["outcome"] == "blocked_duplicate"
