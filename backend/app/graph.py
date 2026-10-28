"""The agent, as a LangGraph state machine.

extract -> investigate <-> tools -> assess -> (pay | human_review | reject)
                                              human_review -> (pay | reject)
"""
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy, interrupt

from . import config, erp, policy
from .schemas import Assessment, Invoice
from .tools import TOOLS

MAX_TOOL_ROUNDS = 6

EXTRACT_PROMPT = (
    "You extract structured data from vendor invoices. Copy identifiers exactly. "
    "If a field is not present, leave it null. Never invent a PO number."
)

INVESTIGATE_PROMPT = (
    "You are an accounts-payable agent verifying an invoice before payment.\n"
    "Use the tools to: 1) look up the vendor, 2) check for a duplicate invoice, "
    "3) match the purchase order if the invoice has one. Call tools until you have the facts, "
    "then reply with a short summary of what you found. Do not decide yet."
)

ASSESS_PROMPT = (
    "Now decide, based only on the tool results above.\n"
    "- reject: vendor is blocked, or the invoice was already paid\n"
    "- review: vendor not found, no PO, PO mismatch (vendor, status or amount), or anything unclear\n"
    "- approve: active vendor, not a duplicate, PO matched\n"
    "Risk is low only when you approve with no issues at all."
)


class State(TypedDict, total=False):
    run_id: str
    invoice_text: str
    invoice: dict
    messages: Annotated[list[AnyMessage], add_messages]
    assessment: dict
    human: dict
    payment: dict
    outcome: str


def build_graph(llm=None, checkpointer=None):
    if llm is None:
        from langchain.chat_models import init_chat_model

        llm = init_chat_model(config.model(), temperature=0, timeout=60, max_retries=2)

    extractor = llm.with_structured_output(Invoice)
    agent = llm.bind_tools(TOOLS)
    assessor = llm.with_structured_output(Assessment)

    # --- nodes ---------------------------------------------------------------

    def extract(state: State) -> dict:
        invoice: Invoice = extractor.invoke(
            [SystemMessage(EXTRACT_PROMPT), HumanMessage(state["invoice_text"])]
        )
        return {
            "invoice": invoice.model_dump(),
            "messages": [
                SystemMessage(INVESTIGATE_PROMPT),
                HumanMessage(f"Invoice to verify:\n{invoice.model_dump_json(indent=2)}"),
            ],
        }

    def investigate(state: State) -> dict:
        return {"messages": [agent.invoke(state["messages"])]}

    def assess(state: State) -> dict:
        result: Assessment = assessor.invoke(state["messages"] + [HumanMessage(ASSESS_PROMPT)])
        return {"assessment": result.model_dump()}

    def human_review(state: State) -> dict:
        # Pauses the run here. The checkpointer saves state; the API resumes it
        # later with Command(resume={...}) and that dict becomes `decision`.
        decision = interrupt({"invoice": state["invoice"], "assessment": state["assessment"]})
        return {"human": decision}

    def pay(state: State) -> dict:
        inv = state["invoice"]
        vendor = erp.find_vendor(inv["vendor_name"])
        vendor_id = vendor["id"] if vendor["found"] else f"NEW:{inv['vendor_name']}"
        result = erp.pay_invoice(vendor_id, inv["invoice_number"], inv["total"], state["run_id"])
        outcome = "paid" if result["status"] == "paid" else "blocked_duplicate"
        return {"payment": result, "outcome": outcome}

    def reject(state: State) -> dict:
        return {"outcome": "rejected"}

    # --- edges ---------------------------------------------------------------

    def after_investigate(state: State) -> str:
        last = state["messages"][-1]
        rounds = sum(1 for m in state["messages"] if m.type == "ai")
        if getattr(last, "tool_calls", None) and rounds <= MAX_TOOL_ROUNDS:
            return "tools"
        return "assess"

    def after_assess(state: State) -> str:
        return policy.route_after_assessment(
            state["invoice"], state["assessment"], config.auto_approve_limit()
        )

    def after_human(state: State) -> str:
        return policy.route_after_human(state["human"])

    llm_retry = RetryPolicy(max_attempts=3)  # provider 429s / timeouts
    erp_retry = RetryPolicy(max_attempts=3, retry_on=erp.TransientERPError)

    g = StateGraph(State)
    g.add_node("extract", extract, retry_policy=llm_retry)
    g.add_node("investigate", investigate, retry_policy=llm_retry)
    # Tools already retry inside erp.py; if an ERP call still fails, retry the whole step.
    g.add_node("tools", ToolNode(TOOLS), retry_policy=erp_retry)
    g.add_node("assess", assess, retry_policy=llm_retry)
    g.add_node("human_review", human_review)
    g.add_node("pay", pay, retry_policy=erp_retry)
    g.add_node("reject", reject)

    g.add_edge(START, "extract")
    g.add_edge("extract", "investigate")
    g.add_conditional_edges("investigate", after_investigate, ["tools", "assess"])
    g.add_edge("tools", "investigate")
    g.add_conditional_edges("assess", after_assess, ["pay", "human_review", "reject"])
    g.add_conditional_edges("human_review", after_human, ["pay", "reject"])
    g.add_edge("pay", END)
    g.add_edge("reject", END)

    return g.compile(checkpointer=checkpointer)
