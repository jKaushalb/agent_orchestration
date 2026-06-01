import React, { useState } from "react";
import ChatPanel from "./ChatPanel.jsx";
import AgentsPanel from "./AgentsPanel.jsx";
import WorkflowBuilder from "./WorkflowBuilder.jsx";

export default function App() {
  // bump to tell the chat panel to refresh its agent/workflow target list
  const [version, setVersion] = useState(0);
  const [view, setView] = useState("chat");

  return (
    <div className="app">
      <header className="topbar">
        <span className="logo">◆ Agent Platform</span>
        <nav className="nav">
          <button className={view === "chat" ? "active" : ""} onClick={() => setView("chat")}>
            Chat
          </button>
          <button className={view === "builder" ? "active" : ""} onClick={() => setView("builder")}>
            Workflow Builder
          </button>
        </nav>
        <span className="subtitle">multi-agent orchestration · local</span>
      </header>

      {view === "chat" ? (
        <div className="layout">
          <ChatPanel version={version} />
          <AgentsPanel onChange={() => setVersion((v) => v + 1)} />
        </div>
      ) : (
        <WorkflowBuilder onChange={() => setVersion((v) => v + 1)} />
      )}
    </div>
  );
}
