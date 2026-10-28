"""App database: runs, run events, and the ERP payment ledger (SQLite).

One file, one lock. Good enough for a single-process MVP; swap for Postgres
when you run more than one API worker.
"""
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,      -- same key => same run, never a second one
    invoice_text    TEXT NOT NULL,
    status          TEXT NOT NULL,             -- queued | running | awaiting_approval | completed | failed
    outcome         TEXT,                      -- paid | rejected | blocked_duplicate
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  TEXT NOT NULL,
    ts      REAL NOT NULL,
    node    TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, id);
CREATE TABLE IF NOT EXISTS payments (
    vendor_id      TEXT NOT NULL,
    invoice_number TEXT NOT NULL,
    amount         REAL NOT NULL,
    run_id         TEXT NOT NULL,
    paid_at        REAL NOT NULL,
    PRIMARY KEY (vendor_id, invoice_number)    -- the idempotency guarantee for payments
);
"""

# An invoice that was already paid last month, so the duplicate check has something to find.
SEED_PAYMENTS = [("V001", "INV-778", 5000.0, "seed", 0.0)]

TERMINAL = {"completed", "failed"}


def db_path() -> str:
    return os.path.join(config.data_dir(), "app.db")


@contextmanager
def conn():
    with _lock:
        c = sqlite3.connect(db_path(), timeout=10)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        c.executemany("INSERT OR IGNORE INTO payments VALUES (?,?,?,?,?)", SEED_PAYMENTS)


# ---------- runs ----------

def create_run(idempotency_key: str, invoice_text: str) -> tuple[dict, bool]:
    """Returns (run, created). A repeated key returns the existing run with created=False."""
    now = time.time()
    run_id = uuid.uuid4().hex[:12]
    with conn() as c:
        try:
            c.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                (run_id, idempotency_key, invoice_text, "queued", None, now, now),
            )
            created = True
        except sqlite3.IntegrityError:
            created = False
        row = c.execute("SELECT * FROM runs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
    return dict(row), created


def get_run(run_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT id, status, outcome, created_at, updated_at, substr(invoice_text,1,80) AS preview "
            "FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_status(run_id: str, status: str, outcome: str | None = None) -> None:
    with conn() as c:
        c.execute(
            "UPDATE runs SET status=?, outcome=COALESCE(?, outcome), updated_at=? WHERE id=?",
            (status, outcome, time.time(), run_id),
        )


def transition(run_id: str, from_status: str, to_status: str) -> bool:
    """Compare-and-set on status. Two approvals racing on one run: only one wins."""
    with conn() as c:
        cur = c.execute(
            "UPDATE runs SET status=?, updated_at=? WHERE id=? AND status=?",
            (to_status, time.time(), run_id, from_status),
        )
    return cur.rowcount == 1


# ---------- events ----------

def add_event(run_id: str, node: str, payload) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO events (run_id, ts, node, payload) VALUES (?,?,?,?)",
            (run_id, time.time(), node, json.dumps(payload, default=str)),
        )


def list_events(run_id: str, after: int = 0) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id", (run_id, after)
        ).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]
