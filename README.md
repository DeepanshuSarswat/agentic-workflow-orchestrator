# Agentic Workflow Orchestrator

An AI agent that approves vendor invoices, with a human in the loop for anything risky.

It reads an invoice, verifies it against a mock ERP using tool calls (vendor, duplicate check, purchase-order match), and proposes a decision. A deterministic policy then decides whether it can auto-pay, must reject, or must pause for a human. Runs are checkpointed, payments are idempotent, flaky ERP calls retry, and an eval suite gates CI.

<!-- Record a 2-minute demo (Clean → paid, Large → approve → paid), save it as docs/demo.gif, then replace this comment with:
![Demo](docs/demo.gif)
-->

**Stack:** React + TypeScript (Vite) · FastAPI · LangGraph · SQLite · any LangChain chat model (Gemini, Claude, GPT)

```
extract ──► investigate ◄──► tools          (ReAct tool loop)
                 │
                 ▼
              assess ──► policy ──┬──► pay ──► end
                                  ├──► reject ──► end
                                  └──► human_review ── interrupt() ── resume ──┬──► pay
                                                                               └──► reject
```

## How it works

| Step | Who does it | What happens |
| --- | --- | --- |
| Submit | You | Paste invoice text. The browser attaches a unique idempotency key. |
| Save run | Python | The run is stored; a repeated key returns the existing run instead of starting a new one. |
| Extract | AI | Raw text becomes a typed `Invoice` object (vendor, number, PO, total, line items). |
| Investigate | AI + Python | The AI decides which tools to call; Python runs them against the mock ERP and returns the results. |
| Assess | AI | Recommends approve, review or reject, with reasons grounded in the tool results. |
| Policy | Python | Hard rules decide. They can only make the outcome stricter than the AI's suggestion. |
| Human review | You | Risky invoices pause. Approve or reject, and the run resumes from its checkpoint. |
| Pay | Python | Writes to the payment ledger exactly once. |

**The LLM proposes, deterministic code decides, humans handle the exceptions.**

## What it demonstrates

| Concern | Where |
| --- | --- |
| Tool-calling agent (LangGraph `ToolNode` loop) | `backend/app/graph.py`, `tools.py` |
| Structured outputs (Pydantic) | `backend/app/schemas.py` |
| Rules over LLM judgement | `backend/app/policy.py` |
| Human-in-the-loop (`interrupt` + `Command(resume=…)`) | `graph.py` → `human_review`, `main.py` → `/decision` |
| Idempotent API (`idempotency_key` unique) | `db.create_run`, `POST /runs` |
| Idempotent payment (ledger primary key) | `erp.pay_invoice` |
| Exactly-once approval (compare-and-set) | `db.transition`, `POST /runs/{id}/decision` |
| Retries with backoff (tenacity + LangGraph `RetryPolicy`) | `erp.py`, `graph.py` |
| LLM timeouts (slow or overloaded provider fails the run instead of hanging) | `graph.py` |
| Checkpointing, resume-from-failure, history | `runner.py` (`SqliteSaver`), `POST /runs/{id}/retry` |
| Live step streaming (SSE) | `GET /runs/{id}/stream`, `frontend/src/api.ts` |
| Evals: accuracy, false approvals, consistency | `evals/run_evals.py`, `evals/dataset.jsonl` |
| CI gate | `.github/workflows/ci.yml` |

## Run it

Requires Python 3.10+ and Node 20+.

```bash
cp .env.example backend/.env      # add a Gemini key: aistudio.google.com/apikey (free tier works)
make setup PYTHON=python3.12      # or just `make setup` if python3 is 3.10+
make test                         # 16 tests, no API key needed
make api                          # terminal 1 → http://localhost:8000/docs
make ui                           # terminal 2 → http://localhost:5173
make eval3                        # real model, each case 3x
```

The default model is `google_genai:gemini-3.5-flash`. Change `MODEL` in `backend/.env` to switch to another model or provider; no code changes are needed.

## Demo script (2 minutes)

1. **Clean - auto-pays:** the steps stream live, and the run ends `paid`.
2. **Duplicate - rejected:** the agent finds `INV-778` already in the ledger.
3. **Large - needs approval:** the AI says approve, but ₹80,000 is over the ₹50,000 limit, so the run pauses. Approve it with a comment; it resumes from its checkpoint and pays.
4. Click **Submit** again without changing the key: you get the same run back (`Idempotent-Replay: true`).
5. Set `FLAKY_RATE=0.3` in `backend/.env`, restart the API, and rerun: ERP calls fail and retry, and runs still finish.

The five samples and the ERP records (`backend/app/erp.py`: 3 vendors, 4 purchase orders, one already-paid invoice) are mock data. The agent, tools, rules, checkpointing and idempotency are real.

## Evaluation

`evals/dataset.jsonl` holds 12 labelled invoices: clean, duplicate, blocked vendor, unknown vendor, three kinds of PO mismatch, missing PO, over the limit, and a prompt-injection attempt. `evals/run_evals.py` runs the real agent on each and reports:

- **False approvals:** invoices auto-paid that should not have been. The CI gate requires **zero**.
- **Accuracy:** the share of invoices where the run ended as labelled. The gate requires at least 80%.
- **Inconsistent cases** (with `--repeats 3`): cases where the model gave different answers across runs, because LLM output is non-deterministic.

A stub model that approves everything fails the gate with 9 false approvals, which confirms the gate catches a bad model.

## Design notes

- **Why a policy layer?** The model can be talked into things (see `injection-01` in the dataset). Rules can only make an outcome stricter, so an over-confident model can't move money past the limit or without a PO.
- **Why false approvals as the gate?** A wrong "review" costs a human a minute. A wrong "approve" costs money. Accuracy alone hides that difference.
- **Why are retries safe?** Every write that matters is idempotent: the run (unique key), the approval (compare-and-set), the payment (ledger primary key). Replaying a step can't do it twice.
- **Why a timeout on the LLM?** Provider clients retry overloads quietly. Without a timeout, a run can hang with no error; with one, it fails visibly and can be retried from its checkpoint.

## Known limits

- **No authentication.** Anyone who can reach the API can approve a run, and `reviewer` is self-reported. Production needs auth, role-based approvers, and a four-eyes rule (the submitter can't approve their own invoice).
- **Limits are per invoice.** Splitting one large invoice into several small ones would bypass the approval threshold. Production needs per-vendor aggregate limits.
- **Text input only.** PDF and image invoices would need a file upload; the model can read both with the same `Invoice` schema.
- **Single process.** SQLite plus in-process background tasks. For multiple workers: a Postgres checkpointer (`langgraph-checkpoint-postgres`) and a real job queue.
