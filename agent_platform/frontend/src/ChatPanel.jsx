import React, { useEffect, useRef, useState } from "react";
import { api, streamRun } from "./api.js";

// Stable-ish colour per agent label for the chat chips.
function colorFor(label) {
  let h = 0;
  for (const c of label) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 65% 45%)`;
}

export default function ChatPanel({ version }) {
  const [agents, setAgents] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [target, setTarget] = useState("");
  const [text, setText] = useState("");
  const [image, setImage] = useState(null);
  const [messages, setMessages] = useState([]);
  const [running, setRunning] = useState(false);
  const closeRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    api.listAgents().then(setAgents).catch(() => {});
    api.listWorkflows().then(setWorkflows).catch(() => {});
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

  async function send() {
    if ((!text.trim() && !image) || !target || running) return;
    const payload = { content: text };
    if (target.startsWith("wf:")) payload.workflow_id = target.slice(3);
    else payload.recipient = target.slice(6);
    if (image) payload.attachments = [{ type: "image", data: image }];

    setMessages([
      { id: "local", label: "you", sender: "user", content: text, status: "sent" },
    ]);
    setText("");
    setImage(null);
    setRunning(true);

    try {
      const { run_id } = await api.startRun(payload);
      closeRef.current?.();
      closeRef.current = streamRun(
        run_id,
        (m) => setMessages((prev) => [...prev.filter((x) => x.id !== "local"), m]),
        () => setRunning(false)
      );
    } catch (e) {
      setMessages((prev) => [...prev, { id: "err", label: "error", content: String(e) }]);
      setRunning(false);
    }
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
        <select value={target} onChange={(e) => setTarget(e.target.value)}>
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
        {running && <span className="running">● running…</span>}
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
