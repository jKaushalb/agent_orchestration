import React, { useEffect, useState } from "react";
import { api } from "./api.js";

const BLANK = {
  name: "",
  role: "",
  system_prompt: "You are a helpful agent.",
  model: "gemini/gemini-2.5-flash",
  temperature: 0.2,
  max_output_tokens: 8126,
  tools: [],
  channels: [],
};

export default function AgentsPanel({ onChange }) {
  const [agents, setAgents] = useState([]);
  const [tools, setTools] = useState([]);
  const [models, setModels] = useState([]);
  const [form, setForm] = useState(BLANK);
  const [editId, setEditId] = useState(null);

  function refresh() {
    api.listAgents().then(setAgents).catch(() => {});
  }
  useEffect(() => {
    refresh();
    api.listTools().then(setTools).catch(() => {});
    api.listModels().then(setModels).catch(() => {});
  }, []);

  // "custom" when the current model isn't one of the presets
  const isPreset = models.some((m) => m.id === form.model);
  const modelSelectValue = isPreset ? form.model : "__custom__";

  function set(k, v) {
    setForm((f) => ({ ...f, [k]: v }));
  }
  function toggle(list, key, v) {
    set(list, form[list].includes(v) ? form[list].filter((x) => x !== v) : [...form[list], v]);
  }

  async function save() {
    if (!form.name.trim()) return;
    if (editId) await api.updateAgent(editId, form);
    else await api.createAgent(form);
    setForm(BLANK);
    setEditId(null);
    refresh();
    onChange && onChange();
  }
  function edit(a) {
    setForm({ ...BLANK, ...a });
    setEditId(a.id);
  }
  async function remove(id) {
    await api.deleteAgent(id);
    if (editId === id) {
      setForm(BLANK);
      setEditId(null);
    }
    refresh();
    onChange && onChange();
  }

  return (
    <aside className="agents">
      <h2>Agents</h2>
      <div className="agent-list">
        {agents.map((a) => (
          <div key={a.id} className="agent-card">
            <div>
              <strong>{a.name}</strong>
              <span className="role">{a.role}</span>
              <div className="muted">{a.model}</div>
              <div className="tags">{(a.tools || []).map((t) => <span key={t}>{t}</span>)}</div>
            </div>
            <div className="actions">
              <button onClick={() => edit(a)}>edit</button>
              <button className="danger" onClick={() => remove(a.id)}>×</button>
            </div>
          </div>
        ))}
        {agents.length === 0 && <div className="muted">No agents yet — create one below.</div>}
      </div>

      <h3>{editId ? "Edit agent" : "New agent"}</h3>
      <div className="form">
        <input placeholder="name" value={form.name} onChange={(e) => set("name", e.target.value)} />
        <input placeholder="role" value={form.role} onChange={(e) => set("role", e.target.value)} />
        <label className="field">model
          <select
            value={modelSelectValue}
            onChange={(e) => {
              const v = e.target.value;
              set("model", v === "__custom__" ? "" : v);
            }}
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
            <option value="__custom__">Custom…</option>
          </select>
        </label>
        {!isPreset && (
          <input
            placeholder="custom litellm model id, e.g. gemini/gemini-2.5-flash"
            value={form.model}
            onChange={(e) => set("model", e.target.value)}
          />
        )}
        <textarea
          placeholder="system prompt"
          value={form.system_prompt}
          onChange={(e) => set("system_prompt", e.target.value)}
        />
        <div className="row">
          <label>temp
            <input type="number" step="0.1" min="0" max="2" value={form.temperature}
              onChange={(e) => set("temperature", parseFloat(e.target.value))} />
          </label>
          <label>max tokens
            <input type="number" value={form.max_output_tokens}
              onChange={(e) => set("max_output_tokens", parseInt(e.target.value || "0", 10))} />
          </label>
        </div>

        <div className="checks">
          <span className="checks-label">tools</span>
          {tools.map((t) => (
            <label key={t}>
              <input type="checkbox" checked={form.tools.includes(t)}
                onChange={() => toggle("tools", t)} /> {t}
            </label>
          ))}
        </div>

        <div className="checks">
          <span className="checks-label">channels</span>
          {["web", "telegram"].map((c) => (
            <label key={c}>
              <input type="checkbox" checked={form.channels.includes(c)}
                onChange={() => toggle("channels", c)} /> {c}
            </label>
          ))}
        </div>

        <div className="row">
          <button onClick={save}>{editId ? "Save" : "Create"}</button>
          {editId && <button onClick={() => { setForm(BLANK); setEditId(null); }}>Cancel</button>}
        </div>
      </div>
    </aside>
  );
}
