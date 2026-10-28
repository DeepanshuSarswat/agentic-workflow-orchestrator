"""Drives graph runs in the background and records every step as an event."""
import os
import sqlite3

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from . import config, db
from .graph import build_graph

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        path = os.path.join(config.data_dir(), "checkpoints.db")
        saver = SqliteSaver(sqlite3.connect(path, check_same_thread=False))
        _graph = build_graph(checkpointer=saver)
    return _graph


def set_graph(graph) -> None:
    """Tests and evals inject a graph built with a stub LLM or in-memory checkpointer."""
    global _graph
    _graph = graph


def _cfg(run_id: str) -> dict:
    # thread_id = run_id: one checkpoint history per run
    return {"configurable": {"thread_id": run_id}}


def to_jsonable(value):
    if isinstance(value, BaseMessage):
        return {
            "type": value.type,
          "content": str(value.text),
            "tool_calls": getattr(value, "tool_calls", None) or None,
            "name": getattr(value, "name", None),
        }
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def _drive(run_id: str, graph_input) -> None:
    graph = get_graph()
    db.set_status(run_id, "running")
    try:
        for chunk in graph.stream(graph_input, _cfg(run_id), stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    db.add_event(run_id, "awaiting_approval", to_jsonable(update[0].value))
                    db.set_status(run_id, "awaiting_approval")
                    return
                db.add_event(run_id, node, to_jsonable(update))
        final = graph.get_state(_cfg(run_id)).values
        db.set_status(run_id, "completed", final.get("outcome"))
    except Exception as exc:  # recorded, never swallowed silently
        db.add_event(run_id, "error", {"error": f"{type(exc).__name__}: {exc}"})
        db.set_status(run_id, "failed")


def start(run_id: str, invoice_text: str) -> None:
    _drive(run_id, {"run_id": run_id, "invoice_text": invoice_text})


def resume(run_id: str, decision: dict) -> None:
    _drive(run_id, Command(resume=decision))


def retry(run_id: str) -> None:
    # Input None = continue from the last saved checkpoint, not from scratch.
    _drive(run_id, None)


def history(run_id: str) -> list[dict]:
    graph = get_graph()
    return [
        {
            "checkpoint_id": snap.config["configurable"]["checkpoint_id"],
            "step": snap.metadata.get("step"),
            "next": list(snap.next),
            "created_at": snap.created_at,
        }
        for snap in graph.get_state_history(_cfg(run_id))
    ]
