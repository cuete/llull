import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initApiFetchLogger } from "./lib/apiFetchLogger";
import { msalInstance, processRedirectResponse } from "./lib/msal";
import "./styles/global.css";

// Initialize fetch logger before any requests happen
initApiFetchLogger();

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Root element not found");

// MSAL must finish initializing before any other MSAL API is used, and the
// redirect response (if we're landing back here after loginRedirect) must be
// processed before the app renders, so AuthGate sees the resulting account.
void msalInstance
  .initialize()
  .then(() => processRedirectResponse())
  .then(() => {
    createRoot(rootEl).render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  });
