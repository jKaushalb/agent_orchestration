import React, { useEffect, useRef, useState } from "react";
import { api, streamRun } from "./api.js";

// Stable-ish colour per agent label for the chat chips.
function colorFor(label) {
  let h = 0;
  for (const c of label) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 65% 45%)`;
}

function runLabel(r) {
  const when = new Date(r.created_at).toLocaleString();
  const topic = (r.topic || "(no topic)").slice(0, 40);
  return `[${r.status}] ${topic} — $${(r.cost || 0).toFixed(4)} — ${when}`;
}

function usd(n) {
  return `$${Number(n || 0).toFixed(4)}`;
}

export default function ChatPanel({ version }) {
  const [agents, setAgents] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [runs, setRuns] = useState([]);
  const [target, setTarget] = useState("");
  const [text, setText] = useState("");
  const [image, setImage] = useState(null);
  const [messages, setMessages] = useState([]);
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState(null);
  const [maxLoops, setMaxLoops] = useState(3);
  const [cost, setCost] = useState(0);
  const closeRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    api.listAgents().then(setAgents).catch(() => {});
    api.listWorkflows().then(setWorkflows).catch(() => {});
    refreshRuns();
  }, [version]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // default target to first workflow, else first agent
  useEffect(() => {
    if (!target) {
      if (workflows[0]) setTarget(`wf:${workflows[0].id}`);
      else if (agents[0]) setTarget(`agent:${agents[0].id}`);
    }
  }, [agents, workflows]);

  function refreshRuns() {
    api.listRuns().then(setRuns).catch(() => {});
  }

  // pull the run's accumulated cost (sum of every sub-agent's cost)
  function refreshCost(id) {
    api.getRun(id).then((r) => setCost(r.cost || 0)).catch(() => {});
  }

  function streamInto(id, onDone) {
    closeRef.current?.();
    closeRef.current = streamRun(
      id,
      (m) => {
        setMessages((prev) => [...prev.filter((x) => x.id !== "local" && x.id !== m.id), m]);
        refreshCost(id); // update running total as each agent finishes
      },
      () => { setRunning(false); refreshRuns(); refreshCost(id); onDone && onDone(); }
    );
  }

  async function send() {
    if ((!text.trim() && !image) || !target || running) return;
    const payload = { content: text, max_loops: Number(maxLoops) || 0 };
    if (target.startsWith("wf:")) payload.workflow_id = target.slice(3);
    else payload.recipient = target.slice(6);
    if (image) payload.attachments = [{ type: "image", data: image }];

    setMessages([{ id: "local", label: "you", sender: "user", content: text, status: "sent" }]);
    setText("");
    setImage(null);
    setRunning(true);
    setCost(0);

    try {
      const { run_id } = await api.startRun(payload);
      setRunId(run_id);
      refreshRuns();
      streamInto(run_id);
    } catch (e) {
      setMessages((prev) => [...prev, { id: "err", label: "error", content: String(e) }]);
      setRunning(false);
    }
  }

  // load a past or active session
  async function loadRun(id) {
    closeRef.current?.();
    if (!id) { setRunId(null); setMessages([]); setRunning(false); return; }
    setRunId(id);
    const [msgs, run] = await Promise.all([api.getMessages(id), api.getRun(id)]);
    setMessages(msgs);
    setCost(run.cost || 0);
    if (run.status === "running") {
      setRunning(true);
      streamInto(id);
    } else {
      setRunning(false);
    }
  }

  async function stop() {
    if (!runId) return;
    await api.stopRun(runId);
    closeRef.current?.();
    setRunning(false);
    refreshRuns();
  }

  function newSession() {
    closeRef.current?.();
    setRunId(null);
    setMessages([]);
    setRunning(false);
    setCost(0);
  }

  function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setImage(String(reader.result).split(",")[1]); // base64 body
    reader.readAsDataURL(file);
  }

  return (
    <section className="chat">
      <div className="chat-controls">
        <select value={target} onChange={(e) => setTarget(e.target.value)} title="where new requests go">
          <optgroup label="Workflows">
            {workflows.map((w) => (
              <option key={w.id} value={`wf:${w.id}`}>⚙ {w.name}</option>
            ))}
          </optgroup>
          <optgroup label="Agents (direct)">
            {agents.map((a) => (
              <option key={a.id} value={`agent:${a.id}`}>{a.name}</option>
            ))}
          </optgroup>
        </select>

        <select className="sessions" value={runId || ""} onChange={(e) => loadRun(e.target.value)}
          title="past sessions">
          <option value="">— sessions ({runs.length}) —</option>
          {runs.map((r) => (
            <option key={r.id} value={r.id}>{runLabel(r)}</option>
          ))}
        </select>

        <label className="turns" title="max feedback-loop turns before the run auto-stops">
          loops
          <input type="number" min="0" value={maxLoops}
            onChange={(e) => setMaxLoops(e.target.value)} />
        </label>

        <button className="ghost" onClick={newSession}>＋ New</button>
        {running
          ? <button className="danger" onClick={stop}>■ Stop</button>
          : <span className="muted">idle</span>}
        {running && <span className="running">● running…</span>}
        <span className="cost" title="total cost of this run (sum of all agents)">
          {usd(cost)}
        </span>
      </div>

      <div className="messages">
        {messages.length === 0 && (
          <div className="empty">Pick a target, type a request, and watch the agents talk.</div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.sender === "user" ? "from-user" : ""}`}>
            <span className="chip" style={{ background: colorFor(m.label || "?") }}>
              {m.label}
            </span>
            <div className="bubble">{m.content}</div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="composer">
        <textarea
          value={text}
          placeholder="Ask the agents… (Enter to send, Shift+Enter for newline)"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <div className="composer-row">
          <label className="file">
            📎 {image ? "image attached" : "image"}
            <input type="file" accept="image/*" onChange={onFile} hidden />
          </label>
          <button onClick={send} disabled={running}>Send</button>
        </div>
      </div>
    </section>
  );
}
