import React, { useState } from "react";
import ChatPanel from "./ChatPanel.jsx";
import AgentsPanel from "./AgentsPanel.jsx";

export default function App() {
  // bump to tell the chat panel to refresh its agent/workflow target list
  const [version, setVersion] = useState(0);

  return (
    <div className="app">
      <header className="topbar">
        <span className="logo">◆ Agent Platform</span>
        <span className="subtitle">multi-agent orchestration · local</span>
      </header>
      <div className="layout">
        <ChatPanel version={version} />
        <AgentsPanel onChange={() => setVersion((v) => v + 1)} />
      </div>
    </div>
  );
}
