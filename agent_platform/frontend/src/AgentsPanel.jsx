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
  skills: [],
  // flat advanced fields (mapped to nested config on save)
  _scheduleCron: "",
  _schedulePrompt: "",
  _memoryEnabled: false,
  _memoryMax: 10,
  _maxCost: "",
  _blocked: "",
};

// flat form fields -> agent payload (nested config objects)
function toPayload(f) {
  const skills = f.skills;
  const schedule = f._scheduleCron && f._schedulePrompt
    ? { cron: f._scheduleCron, prompt: f._schedulePrompt }
    : null;
  const memory_config = f._memoryEnabled
    ? { enabled: true, max_items: Number(f._memoryMax) || 10 }
    : null;
  const guardrails = {};
  if (f._maxCost) guardrails.max_cost_usd = Number(f._maxCost);
  if (f._blocked.trim())
    guardrails.blocked_words = f._blocked.split(",").map((w) => w.trim()).filter(Boolean);
  return {
    name: f.name, role: f.role, system_prompt: f.system_prompt, model: f.model,
    temperature: f.temperature, max_output_tokens: f.max_output_tokens,
    tools: f.tools, channels: f.channels, skills,
    schedule, memory_config,
    guardrails: Object.keys(guardrails).length ? guardrails : null,
  };
}

// agent row -> flat form fields
function fromAgent(a) {
  return {
    ...BLANK, ...a,
    skills: a.skills || [],
    _scheduleCron: a.schedule?.cron || "",
    _schedulePrompt: a.schedule?.prompt || "",
    _memoryEnabled: !!a.memory_config?.enabled,
    _memoryMax: a.memory_config?.max_items || 10,
    _maxCost: a.guardrails?.max_cost_usd ?? "",
    _blocked: (a.guardrails?.blocked_words || []).join(", "),
  };
}

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
  function toggle(list, value) {
    set(list, form[list].includes(value) ? form[list].filter((x) => x !== value) : [...form[list], value]);
  }

  async function save() {
    if (!form.name.trim()) return;
    const payload = toPayload(form);
    if (editId) await api.updateAgent(editId, payload);
    else await api.createAgent(payload);
    setForm(BLANK);
    setEditId(null);
    refresh();
    onChange && onChange();
  }
  function edit(a) {
    setForm(fromAgent(a));
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

        <details className="advanced">
          <summary>Advanced — schedule · memory · guardrails · skills</summary>

          <label className="field">skills (comma-separated)
            <input value={form.skills.join(", ")}
              onChange={(e) => set("skills", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
          </label>

          <div className="adv-group">
            <span className="checks-label">schedule (cron)</span>
            <input placeholder="cron e.g. 0 8 * * *" value={form._scheduleCron}
              onChange={(e) => set("_scheduleCron", e.target.value)} />
            <input placeholder="scheduled prompt" value={form._schedulePrompt}
              onChange={(e) => set("_schedulePrompt", e.target.value)} />
          </div>

          <div className="adv-group">
            <label className="check">
              <input type="checkbox" checked={form._memoryEnabled}
                onChange={(e) => set("_memoryEnabled", e.target.checked)} /> memory enabled
            </label>
            <label className="field">max remembered items
              <input type="number" value={form._memoryMax}
                onChange={(e) => set("_memoryMax", e.target.value)} />
            </label>
          </div>

          <div className="adv-group">
            <span className="checks-label">guardrails</span>
            <label className="field">max cost (USD) per run
              <input type="number" step="0.1" placeholder="e.g. 0.5" value={form._maxCost}
                onChange={(e) => set("_maxCost", e.target.value)} />
            </label>
            <label className="field">blocked words (comma-separated)
              <input value={form._blocked}
                onChange={(e) => set("_blocked", e.target.value)} />
            </label>
          </div>
        </details>

        <div className="row">
          <button onClick={save} disabled={!form.name.trim()}>
            {editId ? "Save" : "Create"}
          </button>
          {editId && <button onClick={() => { setForm(BLANK); setEditId(null); }}>Cancel</button>}
          {!form.name.trim() && <span className="muted">enter a name first</span>}
        </div>
      </div>
    </aside>
  );
}
