# Agentic Workflow Orchestrator

An AI agent that approves vendor invoices, with a human in the loop for anything risky.

It reads an invoice, verifies it against a mock ERP using tool calls (vendor, duplicate check, purchase-order match), proposes a decision, and a deterministic policy decides whether it can auto-pay, must reject, or must pause for a human. Runs are checkpointed, payments are idempotent, flaky ERP calls retry, and an eval suite gates CI.

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
| Checkpointing, resume-from-failure, history | `runner.py` (`SqliteSaver`), `POST /runs/{id}/retry` |
| Live step streaming (SSE) | `GET /runs/{id}/stream`, `frontend/src/api.ts` |
| Evals: accuracy, false approvals, consistency | `evals/run_evals.py`, `evals/dataset.jsonl` |
| CI gate | `.github/workflows/ci.yml` |

## Run it

```bash
cp .env.example backend/.env      # add one API key (Gemini free tier is fine)
make setup
make api                          # http://localhost:8000/docs
make ui                           # http://localhost:5173
make test                         # 16 tests, no API key needed
make eval3                        # real model, each case 3x
```

## Demo script (2 minutes)

1. **Clean - auto-pays:** steps stream live, ends `paid`.
2. **Duplicate - rejected:** the agent finds `INV-778` in the ledger.
3. **Large - needs approval:** run pauses; approve with a comment; it resumes from its checkpoint and pays.
4. Click **Submit** again without changing the key: you get the same run back (`Idempotent-Replay: true`).
5. Set `FLAKY_RATE=0.3`, restart the API, rerun: ERP calls fail and retry, runs still finish.

## Eval results

Fill in after running `make eval3` with your model:

| Model | Accuracy | False approvals | Inconsistent cases |
| --- | --- | --- | --- |
| _your model_ | _x/12_ | _n_ | _n_ |

## Design notes

- **Why a policy layer?** The model can be talked into things (see `injection-01` in the dataset). Rules can only make an outcome stricter, so an over-confident model can't move money past the limit or without a PO.
- **Why false approvals as the gate?** A wrong "review" costs a human a minute. A wrong "approve" costs money. Accuracy hides that difference.
- **Why are retries safe?** Every write that matters is idempotent: the run (unique key), the approval (compare-and-set), the payment (ledger primary key). Replaying a step can't do it twice.
- **Known limits:** single process (SQLite + in-process background tasks). For multiple workers: Postgres checkpointer (`langgraph-checkpoint-postgres`) and a real queue.
