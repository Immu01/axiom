# Axiom Frontend

React 19 and Vite chat client for the Axiom gateway. Messages and non-secret
preferences are stored in browser `localStorage`; gateway/BYOK credentials remain
in tab memory. Creating a share link stores a copy on the backend. The client
supports streaming SSE, provider/model selection, routing
preferences, compare mode, web search, document/image attachments, browser speech
input/output, MCP configuration, and sandboxed HTML artifact previews.

## Development

```bash
npm ci
cp .env.example .env.local
npm run dev
```

Configure `VITE_API_URL` in `.env.local` if the backend is not at
`http://127.0.0.1:8000`. Enter a gateway API key in Settings when required; the
key remains in tab memory and is never stored in browser storage or a frontend
environment variable. Admin-only cockpit actions use the optional admin token
entered in Settings, also kept only in tab memory.

The Tools section includes Resume Analyzer, Code Review, SQL Assistant, Meeting
Notes, and PDF Tutor. Each tool uses the backend provider gateway. SQL queries
and submitted code are never executed. Meeting transcripts are processed in
memory and not saved. PDF Tutor stores extracted text chunks and optional
embeddings in the owner-scoped local SQLite database for document retrieval;
uploaded PDF files themselves are not retained.

## Validation

```bash
npm test
npm run lint
npm run build
```

Keyboard shortcuts: `⌘K` / `Ctrl+K` focuses chat search, `⌘B` / `Ctrl+B`
toggles the sidebar, `⌘N` / `Ctrl+N` starts a new chat, and `Esc` closes open
menus and dialogs.
