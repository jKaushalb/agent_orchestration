import React, { useCallback, useEffect, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  addEdge,
  useNodesState,
  useEdgesState,
} from "reactflow";
import "reactflow/dist/style.css";
import { api } from "./api.js";

const USER_NODE = {
  id: "user",
  position: { x: 480, y: 320 },
  data: { label: "USER ▸ deliver" },
  style: { background: "#223", color: "#cfe", border: "1px solid #5b8cff", borderRadius: 8 },
};

function edgeLabel(d = {}) {
  const parts = [];
  if (d.join) parts.push("join");
  if (d.condition?.contains)
    parts.push(`${d.condition.negate ? "¬" : ""}"${d.condition.contains}"`);
  return parts.join(" · ");
}

export default function WorkflowBuilder({ onChange }) {
  const [agents, setAgents] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [wfId, setWfId] = useState("");
  const [name, setName] = useState("New workflow");
  const [entry, setEntry] = useState([]); // agent ids
  const [nodes, setNodes, onNodesChange] = useNodesState([USER_NODE]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [addId, setAddId] = useState("");
  const [sel, setSel] = useState(null); // {type:'edge'|'node', id}

  useEffect(() => {
    api.listAgents().then(setAgents).catch(() => {});
    refreshWorkflows();
  }, []);

  function refreshWorkflows() {
    api.listWorkflows().then(setWorkflows).catch(() => {});
  }

  const onConnect = useCallback(
    (params) =>
      setEdges((eds) =>
        addEdge({ ...params, data: {}, label: "", animated: true }, eds)
      ),
    [setEdges]
  );

  function addAgentNode() {
    const a = agents.find((x) => x.id === addId);
    if (!a || nodes.some((n) => n.id === a.id)) return;
    setNodes((ns) => [
      ...ns,
      {
        id: a.id,
        position: { x: 80 + ns.length * 40, y: 60 + ns.length * 50 },
        data: { label: a.name },
      },
    ]);
  }

  function toggleEntry(id) {
    setEntry((e) => (e.includes(id) ? e.filter((x) => x !== id) : [...e, id]));
  }

  // --- edge inspector edits ---
  function patchEdge(id, data) {
    setEdges((eds) =>
      eds.map((e) =>
        e.id === id ? { ...e, data, label: edgeLabel(data) } : e
      )
    );
  }

  function load(id) {
    if (!id) return reset();
    api.getWorkflow(id).then((wf) => {
      setWfId(wf.id);
      setName(wf.name);
      const g = wf.graph || {};
      setEntry(g.entry || []);
      const gnodes = (g.nodes || []).map((n) => ({
        id: n.id,
        position: n.position || { x: 100, y: 100 },
        data: { label: n.label || agentName(n.id) },
        style: n.id === "user" ? USER_NODE.style : undefined,
      }));
      if (!gnodes.some((n) => n.id === "user")) gnodes.push(USER_NODE);
      setNodes(gnodes);
      setEdges(
        (g.edges || []).map((e, i) => ({
          id: `e${i}`,
          source: e.source,
          target: e.target,
          animated: true,
          data: { condition: e.condition, join: e.join },
          label: edgeLabel({ condition: e.condition, join: e.join }),
        }))
      );
      setSel(null);
    });
  }

  function agentName(id) {
    return agents.find((a) => a.id === id)?.name || id;
  }

  function reset() {
    setWfId("");
    setName("New workflow");
    setEntry([]);
    setNodes([USER_NODE]);
    setEdges([]);
    setSel(null);
  }

  async function save() {
    const graph = {
      entry,
      nodes: nodes.map((n) => ({ id: n.id, position: n.position, label: n.data.label })),
      edges: edges.map((e) => ({
        source: e.source,
        target: e.target,
        condition: e.data?.condition || null,
        join: !!e.data?.join,
      })),
    };
    const saved = wfId
      ? await api.updateWorkflow(wfId, { name, graph })
      : await api.createWorkflow({ name, graph });
    setWfId(saved.id);
    refreshWorkflows();
    onChange && onChange();
  }

  async function remove() {
    if (!wfId) return;
    await api.deleteWorkflow(wfId);
    reset();
    refreshWorkflows();
    onChange && onChange();
  }

  const selEdge = sel?.type === "edge" ? edges.find((e) => e.id === sel.id) : null;

  return (
    <div className="builder">
      <div className="builder-bar">
        <select value={wfId} onChange={(e) => load(e.target.value)}>
          <option value="">— new workflow —</option>
          {workflows.map((w) => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </select>
        <input value={name} onChange={(e) => setName(e.target.value)} />
        <select value={addId} onChange={(e) => setAddId(e.target.value)}>
          <option value="">add agent…</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <button onClick={addAgentNode}>+ node</button>
        <button onClick={save}>Save</button>
        {wfId && <button className="danger" onClick={remove}>Delete</button>}
      </div>

      <div className="builder-body">
        <div className="canvas">
          <ReactFlow
            nodes={nodes.map((n) => ({
              ...n,
              style: {
                ...(n.style || {}),
                ...(entry.includes(n.id)
                  ? { border: "2px solid #5bd08c", boxShadow: "0 0 0 2px #5bd08c33" }
                  : {}),
              },
            }))}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, n) => setSel({ type: "node", id: n.id })}
            onEdgeClick={(_, e) => setSel({ type: "edge", id: e.id })}
            fitView
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>

        <aside className="inspector">
          <h3>Inspector</h3>
          {!sel && <div className="muted">Select a node or edge. Drag from a node handle to connect.</div>}

          {sel?.type === "node" && sel.id !== "user" && (
            <div className="form">
              <strong>{agentName(sel.id)}</strong>
              <label className="check">
                <input type="checkbox" checked={entry.includes(sel.id)}
                  onChange={() => toggleEntry(sel.id)} />
                entry node (requests enter here)
              </label>
              <button className="danger" onClick={() => {
                setNodes((ns) => ns.filter((n) => n.id !== sel.id));
                setEdges((es) => es.filter((e) => e.source !== sel.id && e.target !== sel.id));
                setEntry((e) => e.filter((x) => x !== sel.id));
                setSel(null);
              }}>remove node</button>
            </div>
          )}

          {selEdge && (
            <div className="form">
              <div className="muted">{agentName(selEdge.source)} → {selEdge.target === "user" ? "USER" : agentName(selEdge.target)}</div>
              <label className="check">
                <input type="checkbox" checked={!!selEdge.data?.join}
                  onChange={(e) => patchEdge(selEdge.id, { ...selEdge.data, join: e.target.checked })} />
                join (barrier: wait for all join inputs)
              </label>
              <label>condition: output contains
                <input
                  value={selEdge.data?.condition?.contains || ""}
                  placeholder="e.g. approved (blank = always)"
                  onChange={(e) => {
                    const v = e.target.value;
                    const condition = v ? { contains: v, negate: selEdge.data?.condition?.negate || false } : null;
                    patchEdge(selEdge.id, { ...selEdge.data, condition });
                  }}
                />
              </label>
              <label className="check">
                <input type="checkbox"
                  checked={!!selEdge.data?.condition?.negate}
                  disabled={!selEdge.data?.condition?.contains}
                  onChange={(e) => patchEdge(selEdge.id, {
                    ...selEdge.data,
                    condition: { ...selEdge.data.condition, negate: e.target.checked },
                  })} />
                negate (fire when it does NOT contain)
              </label>
              <button className="danger" onClick={() => {
                setEdges((es) => es.filter((e) => e.id !== selEdge.id));
                setSel(null);
              }}>remove edge</button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
