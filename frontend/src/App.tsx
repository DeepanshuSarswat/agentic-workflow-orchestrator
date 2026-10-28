import { useCallback, useEffect, useState } from "react";
import { api, streamRun, type Checkpoint, type Run, type RunEvent, type RunSummary } from "./api";

const newKey = () => crypto.randomUUID();

export default function App() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(() => api.listRuns().then(setRuns).catch(() => {}), []);
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <div className="layout">
      <aside>
        <h1>Invoice Agent</h1>
        <NewRun onCreated={(id) => { setSelected(id); refresh(); }} />
        <h2>Runs</h2>
        <ul className="runs">
          {runs.map((r) => (
            <li key={r.id} className={r.id === selected ? "active" : ""} onClick={() => setSelected(r.id)}>
              <StatusBadge status={r.status} outcome={r.outcome} />
              <span className="preview">{r.preview.split("\n")[0]}</span>
            </li>
          ))}
        </ul>
      </aside>
      <main>{selected ? <RunDetail key={selected} id={selected} /> : <p className="empty">Submit an invoice or pick a run.</p>}</main>
    </div>
  );
}

function NewRun({ onCreated }: { onCreated: (id: string) => void }) {
  const [samples, setSamples] = useState<Record<string, string>>({});
  const [text, setText] = useState("");
  const [sample, setSample] = useState("");
  const [key, setKey] = useState(newKey);
  const [note, setNote] = useState("");

  useEffect(() => { api.samples().then(setSamples); }, []);

  async function submit() {
    const run = await api.createRun(text, key);
    // Same key twice returns the original run: that's the idempotency demo.
    setNote(run.status === "queued" ? "" : `Same key: returned existing run ${run.id}`);
    onCreated(run.id);
  }

  return (
    <div className="card">
<select
  value={sample}
  onChange={(e) => { setSample(e.target.value); setText(samples[e.target.value] ?? ""); setKey(newKey()); setNote(""); }}
>
        <option value="" disabled>Load a sample invoice...</option>
        {Object.keys(samples).map((name) => <option key={name}>{name}</option>)}
      </select>
      <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste invoice text" />
      <label className="key">
        Idempotency key <code>{key.slice(0, 8)}</code>
        <button className="link" onClick={() => setKey(newKey())}>new</button>
      </label>
      <button disabled={text.length < 10} onClick={submit}>Submit</button>
      {note && <p className="note">{note}</p>}
    </div>
  );
}

function RunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [history, setHistory] = useState<Checkpoint[]>([]);
  const [tick, setTick] = useState(0); // bump to reload after a decision or retry

  useEffect(() => {
    let close = () => {};
    api.getRun(id).then((r) => {
      setRun(r);
      setEvents(r.events);
      const last = r.events.at(-1)?.id ?? 0;
      close = streamRun(
        id,
        last,
        (e) => setEvents((prev) => [...prev, e]),
        (s) => {
          setRun((prev) => (prev ? { ...prev, ...s } : prev));
          if (s.status !== "running") api.history(id).then(setHistory);
        },
      );
    });
    api.history(id).then(setHistory);
    return () => close();
  }, [id, tick]);

  if (!run) return <p>Loading...</p>;
  const invoice = events.find((e) => e.node === "extract")?.payload.invoice;
  const assessment = [...events].reverse().find((e) => e.node === "assess")?.payload.assessment;

  return (
    <div className="detail">
      <header>
        <h2>Run {run.id}</h2>
        <StatusBadge status={run.status} outcome={run.outcome} />
      </header>

      <div className="grid">
        <section className="card">
          <h3>Invoice (extracted)</h3>
          {invoice ? (
            <dl>
              <dt>Vendor</dt><dd>{invoice.vendor_name}</dd>
              <dt>Number</dt><dd>{invoice.invoice_number}</dd>
              <dt>PO</dt><dd>{invoice.po_number ?? "none"}</dd>
              <dt>Total</dt><dd>{invoice.currency} {invoice.total.toLocaleString()}</dd>
            </dl>
          ) : <p className="muted">Waiting for extraction...</p>}
        </section>
        <section className="card">
          <h3>Agent assessment</h3>
          {assessment ? (
            <>
              <p><b>{assessment.decision}</b> · risk {assessment.risk}</p>
              <ul>{assessment.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
            </>
          ) : <p className="muted">Not assessed yet.</p>}
        </section>
      </div>

      {run.status === "awaiting_approval" && <ApprovalPanel id={id} onDone={() => setTick((t) => t + 1)} />}
      {run.status === "failed" && (
        <div className="card warn">
          This run failed. Retrying resumes from its last checkpoint, not from scratch.
          <button onClick={() => api.retry(id).then(() => setTick((t) => t + 1))}>Retry from checkpoint</button>
        </div>
      )}

      <section className="card">
        <h3>Timeline</h3>
        <ol className="timeline">
          {events.map((e) => <TimelineItem key={e.id} event={e} />)}
        </ol>
      </section>

      <section className="card">
        <h3>Checkpoints ({history.length})</h3>
        <p className="muted">Every step is saved. This is what makes resume, retry and replay possible.</p>
        <ol className="checkpoints">
          {history.map((c) => (
            <li key={c.checkpoint_id}>step {c.step} → next: {c.next.join(", ") || "end"}</li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function ApprovalPanel({ id, onDone }: { id: string; onDone: () => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  async function decide(approved: boolean) {
    setBusy(true);
    try { await api.decide(id, approved, comment); onDone(); } finally { setBusy(false); }
  }
  return (
    <div className="card approval">
      <h3>Needs your approval</h3>
      <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (optional)" />
      <div className="row">
        <button disabled={busy} onClick={() => decide(true)}>Approve and pay</button>
        <button disabled={busy} className="danger" onClick={() => decide(false)}>Reject</button>
      </div>
    </div>
  );
}

const asText = (c: unknown): string =>
  typeof c === "string" ? c : Array.isArray(c) ? c.map((x: any) => x?.text ?? "").join("") : JSON.stringify(c ?? "");

function TimelineItem({ event }: { event: RunEvent }) {
  const p = event.payload ?? {};
  let detail = "";
  if (event.node === "investigate") {
    const msg = p.messages?.[0];
    detail = msg?.tool_calls ? `calls ${msg.tool_calls.map((t: any) => t.name).join(", ")}` : asText(msg?.content);
  } else if (event.node === "tools") {
    detail = (p.messages ?? []).map((m: any) => `${m.name} → ${asText(m.content)}`).join("\n");
  }}

function StatusBadge({ status, outcome }: { status: string; outcome: string | null }) {
  const label = status === "completed" ? outcome ?? "done" : status.replace("_", " ");
  return <span className={`badge b-${outcome ?? status}`}>{label}</span>;
}
