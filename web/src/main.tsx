import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initApiFetchLogger } from "./lib/apiFetchLogger";
import "./styles/global.css";

// Initialize fetch logger before any requests happen
initApiFetchLogger();

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Root element not found");

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
