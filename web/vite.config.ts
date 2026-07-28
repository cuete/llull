import { existsSync, readFileSync } from "fs";
import { resolve } from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Tailscale HTTPS cert for the tailnet hostname (`tailscale cert ...`), if present.
// MSAL/WebCrypto requires a secure context, which plain http:// only satisfies on
// localhost — this lets the same dev server also work over the Tailscale hostname.
const CERT_DIR = resolve(__dirname, "../.certs");
const CERT_PATH = resolve(CERT_DIR, "echeverria.tail013d9a.ts.net.crt");
const KEY_PATH = resolve(CERT_DIR, "echeverria.tail013d9a.ts.net.key");
const hasTailscaleCert = existsSync(CERT_PATH) && existsSync(KEY_PATH);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 3000,
    host: "0.0.0.0",
    allowedHosts: true,
    https: hasTailscaleCert
      ? { cert: readFileSync(CERT_PATH), key: readFileSync(KEY_PATH) }
      : undefined,
  },
});
