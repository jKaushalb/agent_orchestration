import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the FastAPI backend on :8000 so the
// frontend can use same-origin relative URLs (and SSE works cleanly).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/agents": "http://localhost:8000",
      "/runs": "http://localhost:8000",
      "/messages": "http://localhost:8000",
      "/workflows": "http://localhost:8000",
      "/tools": "http://localhost:8000",
    },
  },
});
