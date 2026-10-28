"""HTTP API. Runs execute in background threads; the UI follows them over SSE."""
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import db, runner
from .samples import SAMPLES


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Agentic Workflow Orchestrator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"]
)


class CreateRun(BaseModel):
    invoice_text: str = Field(min_length=10)
    idempotency_key: str = Field(min_length=8, description="Client-generated; reuse it when retrying a request")


class Decision(BaseModel):
    approved: bool
    reviewer: str = "reviewer"
    comment: str = ""


def _run_or_404(run_id: str) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


@app.post("/runs", status_code=202)
def create_run(body: CreateRun, background: BackgroundTasks, response: Response):
    run, created = db.create_run(body.idempotency_key, body.invoice_text)
    if created:
        background.add_task(runner.start, run["id"], body.invoice_text)
    else:
        response.status_code = 200
        response.headers["Idempotent-Replay"] = "true"
    return run


@app.get("/runs")
def list_runs():
    return db.list_runs()


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    run = _run_or_404(run_id)
    return {**run, "events": db.list_events(run_id)}


@app.post("/runs/{run_id}/decision", status_code=202)
def decide(run_id: str, body: Decision, background: BackgroundTasks):
    _run_or_404(run_id)
    # Compare-and-set: a double click or two reviewers can't resume the run twice.
    if not db.transition(run_id, "awaiting_approval", "running"):
        raise HTTPException(409, "run is not awaiting approval")
    db.add_event(run_id, "human_decision", body.model_dump())
    background.add_task(runner.resume, run_id, body.model_dump())
    return {"ok": True}


@app.post("/runs/{run_id}/retry", status_code=202)
def retry_run(run_id: str, background: BackgroundTasks):
    _run_or_404(run_id)
    if not db.transition(run_id, "failed", "running"):
        raise HTTPException(409, "only failed runs can be retried")
    background.add_task(runner.retry, run_id)
    return {"ok": True}


@app.get("/runs/{run_id}/history")
def run_history(run_id: str):
    _run_or_404(run_id)
    return runner.history(run_id)


@app.get("/runs/{run_id}/stream")
async def stream(run_id: str, after: int = 0):
    """Server-Sent Events: one `step` event per graph node, then a `status` event."""
    _run_or_404(run_id)

    async def events():
        last_id, last_status = after, None
        while True:
            for ev in db.list_events(run_id, after=last_id):
                last_id = ev["id"]
                yield f"event: step\ndata: {json.dumps(ev, default=str)}\n\n"
            run = db.get_run(run_id)
            if run["status"] != last_status:
                last_status = run["status"]
                yield f"event: status\ndata: {json.dumps({'status': run['status'], 'outcome': run['outcome']})}\n\n"
            if run["status"] in ("completed", "failed", "awaiting_approval"):
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/samples")
def samples():
    return SAMPLES
