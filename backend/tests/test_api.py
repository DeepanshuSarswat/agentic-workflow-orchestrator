from fastapi.testclient import TestClient

from app import db, main, runner


def test_same_idempotency_key_returns_same_run(monkeypatch):
    started = []
    monkeypatch.setattr(runner, "start", lambda run_id, text: started.append(run_id))
    client = TestClient(main.app)
    body = {"invoice_text": "INVOICE INV-1 from Acme", "idempotency_key": "key-12345678"}

    first = client.post("/runs", json=body)
    second = client.post("/runs", json=body)

    assert first.status_code == 202
    assert second.status_code == 200 and second.headers["Idempotent-Replay"] == "true"
    assert first.json()["id"] == second.json()["id"]
    assert started == [first.json()["id"]]  # the work ran once


def test_decision_only_once(monkeypatch):
    monkeypatch.setattr(runner, "resume", lambda run_id, d: None)
    client = TestClient(main.app)
    run, _ = db.create_run("key-abcdefgh", "INVOICE INV-2 from Acme")
    db.set_status(run["id"], "awaiting_approval")

    ok = client.post(f"/runs/{run['id']}/decision", json={"approved": True})
    dup = client.post(f"/runs/{run['id']}/decision", json={"approved": True})
    assert ok.status_code == 202
    assert dup.status_code == 409
