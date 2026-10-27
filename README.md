<div align="center">

# ⚡ Axiom

### Multi-Provider LLM Gateway & Conversational Workspace

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-19.0+-61DAFB.svg?style=flat&logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-8.0+-646CFF.svg?style=flat&logo=vite&logoColor=white)](https://vitejs.dev/)
[![HTTPX](https://img.shields.io/badge/HTTPX-Async_Streaming-109988.svg?style=flat)](https://www.python-httpx.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active_Development-blue.svg?style=flat)](#)

<p align="center">
  <b>Axiom</b> is a self-hostable FastAPI gateway and React chat workspace. It routes chat requests across Groq, Gemini, and OpenRouter, and can attempt to continue a response after an upstream stream fails. Failover is best-effort: providers can differ in output, availability, and latency.
</p>

[Key Features](#-key-features) • [Architecture Deep Dive](#-architecture--dataflow) • [Mid-Stream Failover Mechanics](#-mid-stream-failover-mechanics) • [RAG & Multimodal Pipeline](#-agentic-rag--multimodal-pipeline) • [Quickstart](#-quickstart--installation) • [API Reference](#-api-specification--telemetry) • [Chaos Engineering](#-chaos-engineering--testing)

---

</div>

## 📌 Executive Summary

Modern AI applications suffer from severe upstream vulnerabilities:
1. **HTTP 429 Rate Limits**: Sudden token or request quota exhaustion.
2. **Upstream Degradation & Outages**: Service brownouts, slow first-byte latency, and cloud cold starts.
3. **Mid-Stream Connection Ruptures**: Network drops or server cancellations while generating long-form completions, leaving the user with half-baked, broken answers.
4. **Provider Lock-in & Deprecation**: Dynamic shifts in API endpoints, pricing tiers, and model availability.

**Axiom** acts as an asynchronous inference proxy and presentation interface. It integrates **Groq**, **Google Gemini**, and **OpenRouter** behind a common chat API. When an upstream attempt fails, it applies a status-dependent cooldown and may try another configured provider, key, or model. A continuation can preserve the text already sent, but the next model may repeat or rephrase content; this is not guaranteed seamless recovery.

---

## 🌟 Key Features

- **🛡 Multi-Provider Failover**: Configurable provider priority with cooldowns and circuit breakers. Route preferences include failover, observed latency, configured cost ranking, configured quality ranking, and adaptive routing.
- **🔄 Mid-Stream Continuation**: On some upstream stream failures, sends the visible partial answer to the next model with a continuation prompt. `fix_seam` inserts a separating space at alphanumeric word boundaries; it cannot guarantee no repetition or semantic consistency.
- **🔑 Key Rotation & Health Telemetry**: Supports comma-separated provider keys, round-robin key selection, status-dependent cooldowns, health probes, and provider status reporting.
- **📏 Context Budgeting**: Trims older chat history to a configurable character budget while preserving recent messages, to limit context growth.
- **🧠 Reasoning-Tag Handling**: Parses `<think>...</think>` blocks in the client. The gateway strips these blocks for internal title/query extraction and continuation context; clients should not assume all upstream providers handle reasoning tags identically.
- **🌐 Tavily Web Search**: Optionally rewrites conversational queries, retrieves web snippets, and supplies citation references and source cards. Search results are external/untrusted content.
- **📂 Multimodal Attachments**: Client-side image downscaling and image input; backend extraction supports PDF, DOCX, XLSX, PPTX, text, CSV, and code formats. Uploaded document text is indexed with per-client SQLite full-text search; this is lexical retrieval, not embedding-based RAG. Scanned-PDF OCR is not implemented.
- **🎙 Browser Voice**: Web Speech API speech recognition and speech synthesis, including optional hands-free turn-taking. It is browser-dependent and does not provide streaming TTS or interruption during generation.
- **🧩 Workspace Tools**: Choose configured models in the chat interface, compare responses from multiple providers, preview HTML artifacts, and use encrypted chat backup/sync.
- **🛠 Structured AI Tools**: Resume Analyzer, Code Review, SQL Assistant, Meeting Notes, and PDF Tutor share the provider gateway, SSE streaming, authentication, request limits, and structured result validation. Meeting transcripts are not persisted. PDF Tutor keeps extracted text chunks and optional Gemini embeddings in owner-scoped SQLite; original PDF files are not retained. PDF retrieval uses hybrid vector/FTS ranking when embeddings are available and FTS otherwise.
- **🕹 Admin Cockpit**: Shows provider telemetry and offers admin-protected failure, mid-stream break, and reset controls.
- **🤖 Agent Tools & MCP**: Planner/tool-call loop, web search, document full-text search, image-generation request passthrough, and bounded Python-subset evaluation. Optional MCP servers are restricted to HTTPS/public endpoints unless explicitly allowlisted.
- **🔌 OpenAI-Compatible Gateway**: `POST /v1/chat/completions` and `GET /v1/models` support API-key-authenticated integration with other clients.
- **🗃 SQLite-backed Services**: Daily quotas, issued API-key hashes, shares, opaque encrypted vault payloads, user-scoped document search, and latency observations are persisted in SQLite.
- **📈 Operations**: Prometheus-format metrics, structured JSON event logs, provider probes, request size limits, rate limits, and admin-protected diagnostics.
- **💾 Local-First Chat**: Chats and non-secret preferences remain in browser `localStorage`. Creating a share stores a copy on the backend; encrypted sync stores client-encrypted chat data. Gateway and BYOK credentials entered in settings are kept in tab memory, not saved to localStorage.

---

## 🏛 Architecture & Dataflow

Axiom separates concerns between a reactive client interface and an asynchronous, non-blocking Python backend engine powered by ASGI streaming.

```
                              ┌────────────────────────────────────────┐
                              │            Axiom Frontend              │
                              │   React 19 + Vite 8 + Lucide Icons     │
                              └───────────────────┬────────────────────┘
                                                  │
                               HTTP POST / Stream │ Server-Sent Events (SSE)
                                                  ▼
                              ┌────────────────────────────────────────┐
                              │          FastAPI ASGI Gateway          │
                              │         (AsyncIO / Uvicorn)            │
                              └───────────────────┬────────────────────┘
                                                  │
                 ┌────────────────────────────────┼────────────────────────────────┐
                 │                                │                                │
                 ▼                                ▼                                ▼
  ┌─────────────────────────────┐  ┌─────────────────────────────┐  ┌─────────────────────────────┐
  │      Document Engine        │  │      Agentic Search         │  │     Orchestration Engine    │
  │ • pypdf stream extraction   │  │ • Contextual Reformulation  │  │ • Tuple-based Node Picker   │
  │ • Common text/code formats │  │ • Tavily Web Search API     │  │ • Configurable Routing      │
  │ • Bounded text extraction  │  │ • Untrusted search context  │  │ • Mid-Stream Continuation  │
  └─────────────────────────────┘  └─────────────────────────────┘  └──────────────┬──────────────┘
                                                                                   │
                                  Cascading Inference Cascade                      │
                 ┌─────────────────────────────────────────────────────────────────┤
                 │                                                                 │
                 ▼                                ▼                                ▼
  ┌─────────────────────────────┐  ┌─────────────────────────────┐  ┌─────────────────────────────┐
  │        Tier 1: Groq         │  │    Tier 2: Google Gemini    │  │   Tier 3: OpenRouter Mesh   │
  │ • LPU ultra-low latency     │  │ • High-context Flash 2.0    │  │ • Multi-model distributed   │
  │ • Configured Groq models   │  │ • Configured Gemini models  │  │ • Configured OpenRouter     │
  │ • Provider key rotation    │  │ • Multimodal where supported│  │ • Models change upstream   │
  └─────────────────────────────┘  └─────────────────────────────┘  └─────────────────────────────┘
```

### Inference Cascade Decision Flow

```mermaid
flowchart TD
    A([Incoming Chat Request]) --> B{Requires Multimodal Vision?}
    B -- Yes --> C[Filter Candidate Pool to Vision Models]
    B -- No --> D[Use Full Multi-Provider Model Roster]

    C --> E[Select Provider x Key x Model]
    D --> E

    E --> F{Usable Node Available?}
    F -- No --> G[Emit Terminal SSE Error Event]
    F -- Yes --> H[Initiate HTTPX Async Stream]

    H --> I{First Token Received within Configured Timeout?}
    I -- No / Timeout --> J[Register Node Cooldown]
    J --> E

    I -- Yes --> K[Stream Tokens to Client via SSE]
    K --> L{Stream Broken Mid-Generation?}

    L -- Yes --> M[Record Partial Answer Buffer]
    M --> N[Flag Provider Failure & Apply Cooldown]
    N --> O[Synthesize Continuation Context & Fix Seam]
    O --> E

    L -- No --> P{Stream Finished [DONE]?}
    P -- Yes --> Q[Emit SSE 'done' & Record Success Metric]
    P -- No --> K
```

---

## ⚡ Mid-Stream Failover Mechanics

One useful resilience feature is **attempting to continue a response after an upstream stream fails**.

### The Problem
When Provider A fails partway through a completion:
1. The user has already received and read tokens 1 through 85 on their screen.
2. If the gateway simply retries the entire request on Provider B, the user experiences jarring screen clearing, duplicate text, and wasted latency.
3. If Provider B is prompted to continue, different BPE (Byte Pair Encoding) tokenizers frequently collide at the seam (e.g. `the` + `elephant` resulting in `theelephant` or missing punctuation).

### Best-Effort Continuation

#### 1. Synthetic Continuation Prompt Injection
When an active generator fails mid-stream, Axiom captures the accumulated text buffer `partial` and, when another candidate is available, includes it in a continuation request:

```python
current = list(messages)
if partial:
    current += [
        {"role": "assistant", "content": partial},
        {
            "role": "user",
            "content": (
                "Continue your previous answer from where it stopped. "
                "Do not repeat anything. Do not add any preamble."
            ),
        },
    ]
```

#### 2. Seam Reconciliation (`fix_seam`)
Before emitting the first token received from the recovery provider, Axiom evaluates the character boundary between the end of `partial` and the start of `token`:

```python
def fix_seam(partial: str, token: str) -> str:
    """Prevents alphanumeric word gluing across mismatched model tokenizer seams."""
    if partial and token and not partial[-1].isspace() and token[0].isalnum() and partial[-1].isalnum():
        return " " + token
    return token
```

The client receives an SSE `status` event when a switch occurs. The continuation is best-effort: the new model may repeat or rephrase text, and failover is not guaranteed if no candidate is available.

---

## 🔍 Agentic RAG & Multimodal Pipeline

```
[User Message with Pronouns]
            │
            ▼
┌──────────────────────────────────────────────┐
│  Dual-Pass Contextual Query Reformulation    │  <-- Analyzes last 6 turns & current ISO date
│  make_search_query()                         │  <-- Strips ambiguous references (he, that, etc.)
└──────────────────────┬───────────────────────┘
                       │ Output: Concise 3-10 word search query
                       ▼
┌──────────────────────────────────────────────┐
│  Tavily Search API Engine with Key Failover  │  <-- Traverses comma-separated API key pool
│  web_search()                                │  <-- Collects result titles, URLs, snippets
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│  Context Isolation & Guardrail Wrapper       │  <-- Injected into System Prompt as UNTRUSTED DATA
│  format_context()                            │  <-- Forces [1], [2] citation style
└──────────────────────────────────────────────┘
```

### Handling Retrieved Content
Axiom labels retrieved web content as untrusted context in the model prompt. This is a defense-in-depth measure, not a guarantee against prompt injection or unsafe model output.

### Multimodal Vision Pipeline
1. **Client-Side Pre-processing**: Files dropped or pasted into the composer are intercepted. Images are rendered to an off-screen HTML5 `Canvas`, scaled down so neither dimension exceeds `1280px`, and converted to `image/jpeg` at 80% quality.
2. **Vision Requests**: Image payloads are sent with the chat request and routed according to configured vision-capable provider/model settings. Provider model catalogs change; configure and verify supported models for the keys and account you use.

---

## 📂 Project Structure

```
Axiom/
├── README.md                      # Primary project documentation & architecture guide
├── .github/workflows/tests.yml    # Mocked backend tests, frontend lint and build
├── backend/                       # High-performance FastAPI ASGI server
│   ├── .env.example               # Environment variable blueprint
│   ├── requirements.txt           # Pinned production Python dependencies
│   ├── main.py                    # Gateway endpoints, SSE generator, RAG integration
│   ├── providers.py               # Cascade state machine, cooldown matrix, stream engine
│   ├── search.py                  # Tavily API web search client & citation formatter
│   ├── auth.py / limits.py        # API-key authentication and per-client rate limits
│   ├── context_budget.py          # Chat history trimming
│   ├── store.py                   # SQLite-backed quotas, keys, shares, vault and FTS
│   ├── openai_compat.py           # OpenAI-compatible request/response adapter
│   ├── agent.py / tools.py        # Tool loop and bounded tool implementations
│   ├── mcp_client.py              # Restricted MCP client support
│   ├── metrics.py / logutil.py    # Metrics and structured logging
│   ├── tests/                     # Unit and mocked-provider test suite
│   ├── test_failover.py           # Optional live-provider failover integration test
│   ├── test_midstream.py          # Optional live-provider stream-break integration test
│   └── README.md                  # Backend-specific architecture & developer guide
└── frontend/                      # React 19 + Vite 8 presentation workspace
    ├── index.html                 # Single-page application entrypoint
    ├── vite.config.js             # Vite development/build configuration
    ├── package.json               # Frontend dependencies & build scripts
    ├── README.md                  # Frontend client documentation & shortcuts
    └── src/
        ├── App.jsx                # Core chat interface, composer, cockpit modal
        ├── App.css                # Polished design system (Dark/Light/System)
        ├── main.jsx               # React DOM mounting & typography init
        ├── voice.js               # Browser Web Speech API helpers
        ├── parseThink.js          # Client-side reasoning-tag parser
        └── index.css              # Global resets & font imports
```

---

## 🚀 Quickstart & Installation

### Prerequisites
- **Node.js**: v18.0.0 or higher
- **Python**: v3.10 or higher
- API Keys for one or more providers:
  - [Groq Cloud Console](https://console.groq.com/keys)
  - [Google AI Studio](https://aistudio.google.com/)
  - [OpenRouter](https://openrouter.ai/keys)
  - [Tavily AI Search](https://tavily.com/) *(Optional, for web search)*

---

### Step 1: Backend Setup

```bash
# 1. Navigate to the backend directory
cd backend

# 2. Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your environment configuration
cp .env.example .env
```

Open `.env` and configure your API keys. Multiple keys per provider can be passed as a comma-separated list:

```ini
GROQ_API_KEYS=gsk_key1,gsk_key2
GEMINI_API_KEYS=AIzaSyKey1,AIzaSyKey2
OPENROUTER_API_KEYS=sk-or-v1-key1
TAVILY_API_KEYS=tvly-key1

# Optional provider model overrides (check provider availability for your account)
GROQ_MODEL=openai/gpt-oss-120b
GEMINI_MODEL=gemini-2.0-flash
OPENROUTER_MODEL=minimax/minimax-m3.1-flash:free

# Provider order and timeouts
PROVIDER_ORDER=groq,gemini,openrouter
FIRST_TOKEN_TIMEOUT=8.0
NEXT_TOKEN_TIMEOUT=20.0

# Gateway access and administration
ENVIRONMENT=development
AXIOM_API_KEY=
ADMIN_TOKEN=

# Browser frontend origin and chat context limit
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
CONTEXT_CHAR_BUDGET=48000
```

The complete set of optional controls (routing mode, rate limits, daily quotas,
SQLite path, circuit-breaker thresholds, trusted-proxy handling, and MCP host
allowlist) is documented with defaults and cautions in
[backend/.env.example](backend/.env.example). In production, use HTTPS, set
`ENVIRONMENT=production`, configure a strong `ADMIN_TOKEN` and `AXIOM_API_KEY`,
set `CORS_ORIGINS` to the real frontend origin, and keep all credentials out
of frontend environment variables and source control. Production mode requires
authentication; issue individual API keys when separate user-level data
isolation is needed.

Start the FastAPI application:
```bash
uvicorn main:app --reload --port 8000
```
*The backend API will be available at `http://127.0.0.1:8000`. The interactive
OpenAPI page is at `http://127.0.0.1:8000/docs`.*

---

### Step 2: Frontend Setup

Open a new terminal window:

```bash
# 1. Navigate to the frontend directory
cd frontend

# 2. Install Node dependencies
npm install

# 3. (Optional) Configure the backend URL and admin token
cp .env.example .env.local

# 4. Launch the Vite development server
npm run dev
```

*The application will launch at `http://localhost:5173`.*

---

## 📡 API Specification & Telemetry

Most chat, title, upload, comparison, and OpenAI-compatible routes require an
API key when authentication is enabled. Send it as `Authorization: Bearer
<key>`. Admin-only diagnostics and chaos controls use `X-Admin-Token`.
`/api/health` is a public liveness endpoint. A shared `AXIOM_API_KEY` is
scoped by caller address; use issued user keys for stronger per-user separation.

### 1. Chat Completion Stream
**Endpoint**: `POST /api/chat/stream`
**Media Type**: `text/event-stream`

#### Request Payload
```json
{
  "messages": [
    {
      "role": "user",
      "content": "Compare quantum computing with classical computing.",
      "images": ["data:image/jpeg;base64,..."]
    }
  ],
  "instructions": "Be concise, analytical, and provide a comparison table.",
  "web_search": true
}
```

#### SSE Stream Events Protocol
| Event | Payload Format | Description |
| :--- | :--- | :--- |
| `sources` | `{"query": str, "items": [{"title": str, "url": str}]}` | Emitted when live web search results have been retrieved. |
| `meta` | `{"provider": "groq", "model": "openai/gpt-oss-120b"}` | Identifies the provider and model handling the response. |
| `status` | `{"message": "Switched provider to gemini"}` | Emitted when a failover rescue has taken place. |
| `token` | `{"text": "Quantum computing..."}` | Individual text chunk or CoT `<think>` token. |
| `error` | `{"message": "Axiom is very busy right now..."}` | Emitted when all cascade tiers have exhausted retries. |
| `done` | `{}` | Emitted upon generation completion. |

---

### 2. Document & File Ingestion
**Endpoint**: `POST /api/extract`
**Payload**: `multipart/form-data` with file parameter.
**Supported Extensions**: `.pdf`, `.docx`, `.xlsx`, `.pptx`, `.txt`, `.md`, `.csv`, `.json`, `.py`, `.js`, `.ts`, `.rs`, `.go`, `.cpp`, `.sql`, etc.
**Limit**: 10 MB file size, 20,000 character maximum window.

#### Response
```json
{
  "name": "system_design.pdf",
  "text": "Executive Summary: Distributed consensus protocols...",
  "truncated": false,
  "chars": 14250
}
```

---

### 3. OpenAI-Compatible Chat Completions
**Endpoint**: `POST /v1/chat/completions`

This route accepts the common OpenAI chat-completion message shape and
`stream` option. Authenticate with a Bearer API key. `GET /v1/models` returns
the configured model catalog. Provider-specific options and tool behavior
remain Axiom-specific; this endpoint is not a claim of complete OpenAI API
parity.

### 4. Additional API Routes

| Method | Route | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Public liveness check. |
| `GET` | `/api/models` | Authenticated configured model catalog. |
| `POST` | `/api/chat/compare` | Concurrent multi-provider comparison stream. |
| `POST` | `/api/share`, `GET /api/share/{id}` | Create and read a share link; possession of the ID grants access. |
| `POST` | `/api/vault`, `GET /api/vault/{id}` | Store and retrieve opaque, client-encrypted vault payloads. |
| `GET` | `/api/status`, `/api/stats`, `/api/config-check` | Admin-protected diagnostics. |
| `GET` | `/metrics` | Prometheus-format metrics. |
| `POST`, `GET`, `DELETE` | `/api/admin/keys` | Admin-protected user-key creation, listing, and revocation. |
| `POST` | `/api/debug/fail/{provider}`, `/api/debug/break/{provider}/{n}`, `/api/debug/clear` | Admin-protected chaos controls. |

### 5. System Telemetry & Cockpit
**Endpoint**: `GET /api/stats` (requires the admin token)

Example response shape; counts, fields, and configured providers depend on the
running instance:

#### Response
```json
{
  "started": 1729584000.0,
  "uptime_seconds": 3600,
  "requests": 142,
  "switches": 18,
  "errors": 0,
  "served": {
    "groq": 118,
    "gemini": 20,
    "openrouter": 4
  },
  "failed": {
    "groq": 20,
    "gemini": 4
  },
  "recent_errors": [
    {
      "time": 1729587420.0,
      "provider": "groq",
      "reason": "HTTP 429"
    }
  ],
  "providers": {
    "groq": {
      "model": "openai/gpt-oss-120b",
      "simulated_failure": false,
      "nodes": [
        {"key": 1, "state": "cooling_down", "seconds_left": 45},
        {"key": 2, "state": "ready", "seconds_left": 0}
      ]
    }
  }
}
```

---

## 🧪 Chaos Engineering & Testing

Axiom includes admin-protected controls for testing provider failures and
mid-stream recovery. Do not expose these controls or the admin token publicly.

### Chaos Simulation Endpoints
- `POST /api/debug/fail/{provider}`: Simulates provider failure.
- `POST /api/debug/break/{provider}/{n}`: Simulates an upstream stream break after `{n}` tokens.
- `POST /api/debug/clear`: Clears simulated failures and cooldowns.

Set a strong `ADMIN_TOKEN` to enable admin routes. Debug routes and
`/api/models/{provider}` are disabled if no admin token is configured.

### Automated Test Suites

#### 1. Unit and Mocked-Provider Tests
From the backend directory:
```bash
python -m pip install -r requirements.txt
python -m pytest tests -q
```

The mocked tests do not require provider credentials and do not send requests
to live providers.

#### 2. Frontend Checks
From the frontend directory:
```bash
npm install
npm run lint
npm test
npm run build
```

#### 3. CI
GitHub Actions runs the backend mocked tests and frontend lint/build checks.
For optional live-provider integration checks, start the backend with provider
keys and an admin token, then run `python test_failover.py` or
`python test_midstream.py` from the backend directory. These manual checks
call real upstream services and may incur provider usage charges.

---

## 🔒 Security & Privacy Posture

- **Browser Storage**: Chat history and workspace settings are stored in browser `localStorage`. The application also supports backend share links and encrypted sync; creating a share persists a copy of that chat on the server.
- **Credential Handling**: Provider credentials belong in backend environment configuration. Frontend-entered gateway/BYOK credentials are held in tab memory rather than `localStorage`. Protect the backend and use HTTPS in deployments.
- **Authentication and Limits**: Configure `AXIOM_API_KEY` and `ADMIN_TOKEN`; production mode requires authentication. Chat, title, upload, and admin routes have configurable per-client request limits. Daily quotas and key ownership depend on the configured gateway and key identity.
- **Data Persistence**: SQLite holds operational data including quotas, API-key hashes, shares, opaque encrypted vault payloads, latency observations, and client-scoped extracted document text/FTS. Review `AXIOM_DATA_DIR`, database backups, and retention requirements before deployment.
- **Uploads and Tools**: Uploads are size-limited, extracted text is capped, and document search is scoped to a client identity. The bounded Python tool is not a general-purpose secure execution sandbox. MCP connections enforce HTTPS/public-address checks by default, with explicit host allowlisting for exceptions.
- **CORS and Proxy Trust**: Set `CORS_ORIGINS` to the intended frontend origin. Enable `TRUST_PROXY` only when requests pass through a trusted proxy that overwrites forwarding headers.
- **Operational Caveats**: A shared API key uses the caller address for scoping; behind a proxy this requires correct trusted-proxy configuration. Share IDs are bearer links, so anyone possessing a link can access its shared chat.

---

## ⌨️ Desktop Keyboard Shortcuts

| Shortcut | Scope | Description |
| :--- | :--- | :--- |
| `⌘K` or `Ctrl+K` | Global | Focus conversation search spotlight |
| `⌘B` or `Ctrl+B` | Global | Expand / Collapse navigation sidebar |
| `Enter` | Composer | Dispatch message to cascade engine |
| `Shift + Enter` | Composer | Insert newline in text editor |
| `Esc` | Modals | Close settings, telemetry cockpit, or search |

---

## 📜 License

This project is distributed under the **MIT License**. See [LICENSE](LICENSE) for full details.
