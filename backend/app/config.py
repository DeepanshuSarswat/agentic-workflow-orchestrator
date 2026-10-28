"""Runtime settings. Read from env at call time so tests and evals can override them."""
import os

from dotenv import load_dotenv

load_dotenv()


def model() -> str:
    # Any LangChain "provider:model" string, e.g. "anthropic:claude-sonnet-4-5",
    # "openai:gpt-4.1-mini", "google_genai:gemini-2.5-flash".
    return os.getenv("MODEL", "google_genai:gemini-2.5-flash")


def auto_approve_limit() -> float:
    """Invoices above this total always go to a human, whatever the LLM says."""
    return float(os.getenv("AUTO_APPROVE_LIMIT", "50000"))


def price_tolerance_pct() -> float:
    """Allowed difference between invoice total and PO amount."""
    return float(os.getenv("PRICE_TOLERANCE_PCT", "1.0"))


def flaky_rate() -> float:
    """Probability that a mock ERP call fails with a transient error (demo of retries)."""
    return float(os.getenv("FLAKY_RATE", "0"))


def data_dir() -> str:
    path = os.getenv("DATA_DIR", "data")
    os.makedirs(path, exist_ok=True)
    return path
