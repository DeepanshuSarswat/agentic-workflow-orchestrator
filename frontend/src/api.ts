// Typed client for the FastAPI backend. Every call goes through /api (Vite proxy).

export type RunStatus = "queued" | "running" | "awaiting_approval" | "completed" | "failed";

export interface RunSummary {
  id: string;
  status: RunStatus;
  outcome: string | null;
  created_at: number;
  preview: string;
}

export interface RunEvent {
  id: number;
  run_id: string;
  ts: number;
  node: string;
  payload: any;
}

export interface Run extends RunSummary {
  invoice_text: string;
  idempotency_key: string;
  events: RunEvent[];
}

export interface Checkpoint {
  checkpoint_id: string;
  step: number;
  next: string[];
  created_at: string;
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  samples: () => http<Record<string, string>>("/samples"),
  listRuns: () => http<RunSummary[]>("/runs"),
  getRun: (id: string) => http<Run>(`/runs/${id}`),
  history: (id: string) => http<Checkpoint[]>(`/runs/${id}/history`),
  createRun: (invoice_text: string, idempotency_key: string) =>
    http<Run>("/runs", { method: "POST", body: JSON.stringify({ invoice_text, idempotency_key }) }),
  decide: (id: string, approved: boolean, comment: string) =>
    http(`/runs/${id}/decision`, { method: "POST", body: JSON.stringify({ approved, comment }) }),
  retry: (id: string) => http(`/runs/${id}/retry`, { method: "POST" }),
};

/** Follows a run over Server-Sent Events. Returns a function that closes the stream. */
export function streamRun(
  id: string,
  after: number,
  onStep: (e: RunEvent) => void,
  onStatus: (s: { status: RunStatus; outcome: string | null }) => void,
): () => void {
  const source = new EventSource(`/api/runs/${id}/stream?after=${after}`);
  source.addEventListener("step", (e) => onStep(JSON.parse((e as MessageEvent).data)));
  source.addEventListener("status", (e) => {
    const s = JSON.parse((e as MessageEvent).data);
    onStatus(s);
    if (s.status !== "running" && s.status !== "queued") source.close();
  });
  source.onerror = () => source.close();
  return () => source.close();
}
