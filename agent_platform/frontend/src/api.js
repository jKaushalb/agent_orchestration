// Thin REST client for the backend. Relative URLs -> proxied by Vite in dev.

async function j(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${url} -> ${res.status}`);
  return res.status === 204 ? null : res.json();
}

export const api = {
  listAgents: () => j("GET", "/agents"),
  createAgent: (a) => j("POST", "/agents", a),
  updateAgent: (id, a) => j("PUT", `/agents/${id}`, a),
  deleteAgent: (id) => j("DELETE", `/agents/${id}`),
  listTools: () => j("GET", "/tools"),
  startRun: (payload) => j("POST", "/runs", payload),
  listWorkflows: () => j("GET", "/workflows").catch(() => []),
  getWorkflow: (id) => j("GET", `/workflows/${id}`),
  createWorkflow: (w) => j("POST", "/workflows", w),
  updateWorkflow: (id, w) => j("PUT", `/workflows/${id}`, w),
  deleteWorkflow: (id) => j("DELETE", `/workflows/${id}`),
};

// Subscribe to a run's live message stream (SSE). Returns a close() fn.
export function streamRun(runId, onMessage, onDone) {
  const es = new EventSource(`/messages/stream?run_id=${runId}`);
  es.onmessage = (e) => onMessage(JSON.parse(e.data));
  es.addEventListener("done", (e) => {
    onDone && onDone(JSON.parse(e.data));
    es.close();
  });
  es.onerror = () => es.close();
  return () => es.close();
}
