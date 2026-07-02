import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initApiFetchLogger } from "./lib/apiFetchLogger";
import { initDemoModeGuard } from "./lib/demoModeGuard";
import "./styles/global.css";

// Block mutating requests first (if demo mode is on), then log everything
initDemoModeGuard();
initApiFetchLogger();

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Root element not found");

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
