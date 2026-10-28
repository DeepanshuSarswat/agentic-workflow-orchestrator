"""Runs the real agent (real LLM, mock ERP) over a labelled invoice set.

Prediction = where the run ends up:
  paused for a human -> review | paid -> approve | rejected / blocked -> reject

The metric that matters is FALSE APPROVALS (money paid that should not have been).
Accuracy alone hides it: a model that sends everything to review scores 50% and is
useless; one that is 90% accurate but auto-pays one bad invoice is dangerous.

Usage:  python evals/run_evals.py --repeats 3
Exit code 1 if the gate fails, so CI can block a merge.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="awo-eval-")  # never touch the real ledger

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app import db  # noqa: E402
from app.graph import build_graph  # noqa: E402

LABELS = ["approve", "review", "reject"]


def predict(graph, case_id: str, text: str) -> str:
    cfg = {"configurable": {"thread_id": case_id}}
    for _ in graph.stream({"run_id": case_id, "invoice_text": text}, cfg):
        pass
    state = graph.get_state(cfg)
    if "human_review" in state.next:
        return "review"
    return "approve" if state.values.get("outcome") == "paid" else "reject"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "evals" / "dataset.jsonl"))
    ap.add_argument("--repeats", type=int, default=1, help="run each case N times to measure consistency")
    ap.add_argument("--min-accuracy", type=float, default=0.8)
    ap.add_argument("--max-false-approvals", type=int, default=0)
    args = ap.parse_args()

    cases = [json.loads(line) for line in open(args.dataset) if line.strip()]
    graph = build_graph(checkpointer=InMemorySaver())

    rows, confusion = [], Counter()
    for case in cases:
        preds = []
        for i in range(args.repeats):
            db.init_db()
            with db.conn() as c:  # reset the ledger so case order and repeats don't interact
                c.execute("DELETE FROM payments WHERE run_id != 'seed'")
            t0 = time.time()
            try:
                preds.append(predict(graph, f"{case['id']}-{i}", case["invoice"]))
            except Exception as exc:
                preds.append(f"error:{type(exc).__name__}")
            print(f"  {case['id']:<22} run {i + 1}: {preds[-1]:<8} ({time.time() - t0:.1f}s)")
        majority = Counter(preds).most_common(1)[0][0]
        confusion[(case["expected"], majority)] += 1
        rows.append({**case, "predictions": preds, "majority": majority,
                     "consistent": len(set(preds)) == 1, "correct": majority == case["expected"]})

    n = len(rows)
    accuracy = sum(r["correct"] for r in rows) / n
    false_approvals = [r["id"] for r in rows if r["majority"] == "approve" and r["expected"] != "approve"]
    missed_approvals = [r["id"] for r in rows if r["expected"] == "approve" and r["majority"] != "approve"]
    inconsistent = [r["id"] for r in rows if not r["consistent"]]
    by_tag = defaultdict(list)
    for r in rows:
        for t in r["tags"]:
            by_tag[t].append(r["correct"])

    print("\nConfusion (rows = expected, cols = predicted)")
    print(" " * 10 + "".join(f"{p:>9}" for p in LABELS))
    for e in LABELS:
        print(f"{e:>10}" + "".join(f"{confusion[(e, p)]:>9}" for p in LABELS))
    print(f"\naccuracy           {accuracy:.0%}  ({sum(r['correct'] for r in rows)}/{n})")
    print(f"false approvals    {len(false_approvals)}  {false_approvals}")
    print(f"missed approvals   {len(missed_approvals)}  {missed_approvals}  (cost: human time, not money)")
    if args.repeats > 1:
        print(f"inconsistent cases {len(inconsistent)}  {inconsistent}")
    print("by tag             " + ", ".join(f"{t} {sum(v)}/{len(v)}" for t, v in sorted(by_tag.items())))

    report = {"accuracy": accuracy, "false_approvals": false_approvals, "missed_approvals": missed_approvals,
              "inconsistent": inconsistent, "cases": rows}
    (ROOT / "evals" / "report.json").write_text(json.dumps(report, indent=2))

    passed = accuracy >= args.min_accuracy and len(false_approvals) <= args.max_false_approvals
    print("\nGATE", "PASSED" if passed else "FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
