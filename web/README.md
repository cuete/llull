# Llull Web UI

React + TypeScript SPA for the Llull knowledge management service.

## Tech Stack

- **Vite** — build tool, dev server
- **React 18** + **TypeScript** (strict)
- **React Router v6** — client-side routing
- **@tanstack/react-query** — server state
- **Zustand** — client state
- **Zod** — API response validation
- **mermaid** — knowledge graph rendering
- **marked** — markdown rendering
- **CSS Modules** — scoped styles, no CSS-in-JS

## Setup

```bash
# Install dependencies
npm install

# Copy env template
cp .env.example .env.local

# Start dev server (http://localhost:3000)
npm run dev
```

## Environment

```env
VITE_API_BASE_URL=http://localhost:8000
```

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start dev server on port 3000 (binds 0.0.0.0 for Tailscale) |
| `npm run build` | Production build to `dist/` |
| `npm run test` | Run vitest tests |
| `npm run lint` | ESLint check |

## Structure

```
src/
  components/     # Shared UI (Header, ConfirmDialog, etc.)
  features/
    topics/       # Topic list + topic view
    chat/         # Chat tab with SSE streaming
    map/          # Knowledge graph (Mermaid)
    document/     # Markdown editor with autosave
    sources/      # Source management + add modal
    settings/     # LLM configuration (localStorage)
  hooks/          # useSSEStream, useTheme
  lib/            # api.ts (typed client), types.ts (Zod schemas)
  styles/         # global.css
  App.tsx
  main.tsx
```
