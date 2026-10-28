import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.schemas import Assessment, Invoice  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FLAKY_RATE", "0")
    db.init_db()
    yield


class ScriptedLLM:
    """A stand-in for a chat model, so graph tests run with no API key and no randomness.

    It answers extraction and assessment with fixed objects, and in the tool loop it
    emits `tool_calls` on its first turn and a plain summary afterwards.
    """

    def __init__(self, invoice: dict, tool_calls: list[dict], assessment: dict):
        self.invoice = Invoice(**invoice)
        self.assessment = Assessment(**assessment)
        self.tool_calls = tool_calls

    def with_structured_output(self, schema):
        value = self.invoice if schema is Invoice else self.assessment
        return RunnableLambda(lambda _messages: value)

    def bind_tools(self, _tools):
        def step(messages):
            if not any(m.type == "ai" for m in messages):
                return AIMessage(content="", tool_calls=self.tool_calls)
            return AIMessage(content="Checks complete.")

        return RunnableLambda(step)


@pytest.fixture
def scripted_llm():
    return ScriptedLLM
