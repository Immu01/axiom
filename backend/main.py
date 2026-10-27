import asyncio
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

import agent
import auth
import context_budget
import extract
import limits
import logutil
import metrics
import mcp_client
import openai_compat
import providers
import search
import store
from tools_apps import code_review, meeting_notes, pdf_tutor, resume, sql_assistant
from tools_apps.common import sse


@asynccontextmanager
async def lifespan(_app):
    store._connect()
    providers.restore_routing_telemetry()
    probe_task = asyncio.create_task(_probe_loop())
    yield
    probe_task.cancel()
    await providers.close_client()


async def _probe_loop():
    while True:
        try:
            await asyncio.sleep(float(os.getenv("HEALTH_PROBE_SECS", "90") or 90))
            result = await providers.probe_providers()
            logutil.log("health_probe", **result)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logutil.log("health_probe_error", error=type(e).__name__)


app = FastAPI(title="Axiom", lifespan=lifespan)

CORS_ORIGINS = [
    o.strip().rstrip("/")
    for o in (os.getenv("CORS_ORIGINS") or "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    expose_headers=["Retry-After"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(resume.router)
app.include_router(code_review.router)
app.include_router(sql_assistant.router)
app.include_router(meeting_notes.router)
app.include_router(pdf_tutor.router)

SYSTEM_PROMPT = (
    "You are Axiom, a friendly, helpful and honest AI chat assistant. "
    "Axiom is a multi-provider chatbot: behind the scenes it can run on several different AI models "
    "and switches between them automatically so conversations are not interrupted. "
    "You do not know which specific model is answering at any moment, so never claim to be GPT, "
    "Claude, Gemini or any particular model. "
    "If asked about Axiom's features, architecture, company, pricing or roadmap beyond what is stated here, "
    "say you don't have that information instead of guessing. Never invent facts, links or product details. "
    "Keep answers clear and well organised, and avoid unnecessary blank space. "
    "When web or document sources are provided, cite them as [1], [2] inline."
)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=limits.MAX_MESSAGE_CHARS)
    images: list[Annotated[str, Field(max_length=4_000_000)]] = Field(default_factory=list, max_length=3)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=limits.MAX_MESSAGES)
    instructions: str = Field(default="", max_length=5000)
    memory: str = Field(default="", max_length=4000)
    web_search: bool = False
    agent: bool = False
    tools: bool = False
    route: str = Field(default="", max_length=20)
    provider: str = Field(default="", max_length=32)
    model: str = Field(default="", max_length=80)
    mcp_url: str = Field(default="", max_length=300)
    byok: dict[str, str] = Field(default_factory=dict)
    compare: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def _check_total_size(self):
        if sum(len(m.content) for m in self.messages) > limits.MAX_TOTAL_CHARS:
            raise ValueError("Conversation is too long")
        return self


def require_admin(request: Request, x_admin_token: str = Header(default="")):
    """Protects admin/chaos endpoints. If ADMIN_TOKEN is not set, they are disabled (404)."""
    limits.admin_limiter.check(limits.client_key(request))
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    if not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")


def _known_provider(provider: str):
    if provider not in providers.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")


@app.get("/")
def root():
    return {"message": "Axiom is alive"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def prometheus_metrics(_: None = Depends(require_admin)):
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/api/config-check", dependencies=[Depends(require_admin)])
def config_check():
    return {
        name: {"keys_loaded": len(cfg["keys"]), "model": cfg["model"] or "(not set)"}
        for name, cfg in providers.PROVIDERS.items()
    }


@app.get("/api/status", dependencies=[Depends(require_admin)])
def status():
    return providers.get_status()


@app.get("/api/models")
def catalog(_: dict = Depends(auth.require_user)):
    return {
        name: {
            "models": cfg["models"],
            "vision_models": cfg["vision_models"],
            "active": cfg["model"],
        }
        for name, cfg in providers.PROVIDERS.items()
    }


@app.get("/api/models/{provider}", dependencies=[Depends(require_admin)])
async def list_models(provider: str):
    cfg = providers.PROVIDERS.get(provider)
    if not cfg or not cfg["keys"]:
        raise HTTPException(status_code=404, detail="Unknown provider or no key configured")

    headers = {"Authorization": f"Bearer {cfg['keys'][0]}"}
    r = await providers.get_client().get(cfg["models_url"], headers=headers)

    if r.status_code != 200:
        print("Models error:", provider, r.status_code, r.text[:300])
        raise HTTPException(status_code=502, detail=f"Provider error {r.status_code}")

    data = r.json().get("data", [])
    if provider == "openrouter":
        ids = [m["id"] for m in data if str(m.get("pricing", {}).get("prompt")) == "0"]
    else:
        ids = [m["id"].removeprefix("models/") for m in data]
    return sorted(ids)


@app.post("/api/debug/fail/{provider}", dependencies=[Depends(require_admin)])
def debug_fail(provider: str):
    _known_provider(provider)
    providers.forced_fail.add(provider)
    return {"simulated_failures": sorted(providers.forced_fail)}


@app.post("/api/debug/clear", dependencies=[Depends(require_admin)])
def debug_clear():
    providers.reset_state()
    return {"simulated_failures": [], "cooldowns": "reset"}


@app.post("/api/debug/break/{provider}/{n}", dependencies=[Depends(require_admin)])
def debug_break(provider: str, n: int):
    _known_provider(provider)
    n = max(0, min(n, 5000))
    providers.break_after[provider] = n
    return {"break_after": providers.break_after}


async def make_search_query(messages: list[Message]) -> str:
    """Turns the latest message into a standalone web search query using recent context."""
    from datetime import date

    last = messages[-1].content.strip()
    fallback = last[:200]
    if sum(1 for x in messages if x.role == "user") < 2:
        return fallback

    convo = "\n".join(f"{x.role}: {x.content[:300]}" for x in messages[-6:])
    prompt = [
        {
            "role": "system",
            "content": (
                f"Today is {date.today().isoformat()}. You turn the LAST user message of a conversation "
                "into one standalone web search query. Replace pronouns and vague references (he, she, it, "
                "that, there, them) with the real names or topics from the conversation. Keep it short, "
                "3 to 10 words, and do not add information that was not asked about. "
                "Reply with ONLY the search query: no quotes, no explanation."
            ),
        },
        {"role": "user", "content": convo},
    ]

    async def run() -> str:
        text = ""
        async for event, data in providers.stream_with_failover(prompt, internal=True):
            if event == "token":
                text += data["text"]
            elif event == "error":
                logutil.log("search_rewrite_failed", reason="provider_unavailable")
                return ""
        return text

    try:
        text = await asyncio.wait_for(run(), timeout=8)
    except asyncio.TimeoutError:
        logutil.log("search_rewrite_failed", reason="timeout")
        return fallback

    q = providers.strip_think(text).split("\n")[0].strip().strip("\"'`*# ")
    return q[:200] if len(q) >= 3 else fallback


def to_provider_message(m: Message) -> dict:
    images = [
        u for u in m.images[:3]
        if u.startswith("data:image/") and ";base64," in u[:60] and len(u) < 4_000_000
    ]
    if not images:
        return {"role": m.role, "content": m.content}
    parts = [{"type": "text", "text": m.content}]
    parts += [{"type": "image_url", "image_url": {"url": u}} for u in images]
    return {"role": m.role, "content": parts}


def build_system(req: ChatRequest, sources: list, dropped: int) -> str:
    system = SYSTEM_PROMPT
    if req.instructions.strip():
        system += (
            "\n\nThe user has set these custom instructions. Follow them when reasonable:\n"
            + req.instructions.strip()[:1500]
        )
    if req.memory.strip():
        system += "\n\nProject / chat memory (follow these standing notes):\n" + req.memory.strip()[:2000]
    if sources:
        system += "\n\n" + search.format_context(sources)
    if dropped:
        system += (
            "\n\nNote: the earliest part of this conversation was left out to fit the model's context window. "
            "If the user refers to something you cannot see, say so instead of guessing."
        )
    return system


@app.post("/api/chat/stream", dependencies=[Depends(limits.chat_limit), Depends(limits.chat_body)])
async def chat_stream(req: ChatRequest, user: dict = Depends(auth.require_user)):
    extra = auth.sanitize_byok(req.byok)
    sources = []
    query = ""
    if req.web_search and req.messages:
        query = await make_search_query(req.messages)
        logutil.log("search_query", query_chars=len(query), user_kind=user["kind"])
        sources = await search.web_search(query)
    kept, dropped = context_budget.trim_messages(req.messages)
    system = build_system(req, sources, dropped)
    messages = [{"role": "system", "content": system}] + [to_provider_message(m) for m in kept]
    needs_vision = any(isinstance(x["content"], list) for x in messages)
    mode = req.route or None
    pin = req.provider if req.provider in providers.PROVIDERS else None
    pin_model = req.model or None
    use_agent = req.agent or req.tools
    mcp_url = req.mcp_url if req.mcp_url.startswith("http") else ""
    if use_agent and mcp_url:
        try:
            mcp_url = await mcp_client.validate_endpoint(mcp_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    logutil.log("chat_start", user_kind=user["kind"], agent=use_agent, provider=pin, route=mode)

    async def event_generator():
        if dropped:
            yield sse("context", {"dropped": dropped})
        if sources:
            yield sse("sources", {"query": query, "items": [{"title": s["title"], "url": s["url"], "snippet": s.get("snippet", "")} for s in sources]})
        stream = (
            agent.run_agent(
                messages,
                mcp_url=mcp_url,
                extra_keys=extra,
                mode=mode,
                owner_id=user["id"],
                pin_provider=pin,
                pin_model=pin_model,
            )
            if use_agent
            else providers.stream_with_failover(
                messages, needs_vision, extra_keys=extra, mode=mode, pin_provider=pin, pin_model=pin_model
            )
        )
        chars = 0
        async for event, data in stream:
            if event == "token":
                chars += len(data.get("text") or "")
            yield sse(event, data)
        if chars:
            store.bump_quota(user["id"], requests=0, tokens=max(1, chars // 4))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat/compare", dependencies=[Depends(limits.chat_limit), Depends(limits.chat_body)])
async def chat_compare(req: ChatRequest, user: dict = Depends(auth.require_user)):
    names = [p for p in req.compare if p in providers.PROVIDERS][:3] or list(providers.ORDER[:2])
    query = ""
    sources = []
    if req.web_search:
        query = await make_search_query(req.messages)
        sources = await search.web_search(query)
    kept, dropped = context_budget.trim_messages(req.messages)
    system = build_system(req, sources, dropped)
    messages = [{"role": "system", "content": system}] + [to_provider_message(m) for m in kept]
    extra = auth.sanitize_byok(req.byok)

    async def event_generator():
        yield sse("compare", {"providers": names})
        if dropped:
            yield sse("context", {"dropped": dropped})
        if sources:
            yield sse("sources", {
                "query": query,
                "items": [
                    {"title": source["title"], "url": source["url"], "snippet": source.get("snippet", "")}
                    for source in sources
                ],
            })
        queue: asyncio.Queue = asyncio.Queue()

        async def run_one(slot: int, name: str):
            try:
                async for event, data in providers.stream_with_failover(
                    messages, extra_keys=extra, pin_provider=name
                ):
                    await queue.put((slot, name, event, data))
            except Exception as exc:
                await queue.put((slot, name, "error", {"message": f"Comparison failed: {type(exc).__name__}"}))
            finally:
                await queue.put((slot, name, "finished", {}))

        tasks = [asyncio.create_task(run_one(i, name)) for i, name in enumerate(names)]
        finished = 0
        chars = 0
        try:
            while finished < len(tasks):
                slot, name, event, data = await queue.get()
                if event == "finished":
                    finished += 1
                    continue
                if event == "token":
                    chars += len(data.get("text") or "")
                payload = {**data, "slot": slot, "provider": data.get("provider") or name}
                yield sse("compare_" + event if event in ("token", "meta", "error", "done") else event, payload)
            if chars:
                store.bump_quota(user["id"], requests=0, tokens=max(1, chars // 4))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class TitleRequest(BaseModel):
    question: str = Field(max_length=20000)


@app.post("/api/title", dependencies=[Depends(limits.title_limit)])
async def make_title(req: TitleRequest, _: dict = Depends(auth.require_user)):
    prompt = [
        {
            "role": "system",
            "content": "You write short chat titles of 2 to 5 words. Use a noun phrase in Title Case that names the topic, for example Magnet Basics, Python Function Example, or Recursion Explained. Never start with Understanding or Explaining. Never copy the user sentence. Never use a question mark. Reply with ONLY the title.",
        },
        {"role": "user", "content": "Write a title for a chat that starts with this message:\n\n" + req.question[:500]},
    ]
    text = ""
    async for event, data in providers.stream_with_failover(prompt, internal=True):
        if event == "token":
            text += data["text"]
        elif event == "error":
            raise HTTPException(status_code=502, detail="Could not generate a chat title.")

    title = providers.strip_think(text).split("\n")[0].strip().strip("\"'*#. ?!")
    return {"title": title[:50]}


@app.get("/api/stats", dependencies=[Depends(require_admin)])
def get_stats():
    import time

    s = providers.stats
    return {
        **s,
        "uptime_seconds": int(time.time() - s["started"]),
        "providers": providers.get_status(),
        "routing_mode": providers.ROUTING_MODE,
        "ttft": providers.ewma_ttft,
    }


@app.post("/api/extract", dependencies=[Depends(limits.extract_limit), Depends(limits.extract_body)])
async def extract_file(file: UploadFile = File(...), _: dict = Depends(auth.require_user)):
    result = await extract.extract_upload(file)
    store.index_document(_["id"], result["name"], result["text"])
    return result


class ShareIn(BaseModel):
    title: str = Field(default="Shared chat", max_length=120)
    messages: list[dict]


@app.post("/api/share", dependencies=[Depends(limits.chat_limit)])
def create_share(body: ShareIn, _: dict = Depends(auth.require_user)):
    sid = secrets.token_urlsafe(10)
    clean = []
    for m in body.messages[:80]:
        if m.get("role") not in ("user", "assistant"):
            continue
        sources = []
        for source in m.get("sources", [])[:10] if isinstance(m.get("sources"), list) else []:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "")
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                continue
            sources.append({
                "title": str(source.get("title") or parsed.hostname)[:120],
                "url": url[:2000],
                "snippet": str(source.get("snippet") or "")[:500],
            })
        clean.append({
            "role": m["role"],
            "content": str(m.get("content") or "")[:20000],
            "sources": sources,
        })
    store.save_share(sid, body.title, {"messages": clean})
    return {"id": sid, "url": f"/share/{sid}"}


@app.get("/api/share/{sid}")
def read_share(sid: str):
    data = store.get_share(sid)
    if not data:
        raise HTTPException(status_code=404, detail="Share not found")
    return data


class VaultIn(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    ciphertext: str = Field(max_length=15_000_000)


@app.post("/api/vault", dependencies=[Depends(limits.chat_limit), Depends(limits.chat_body)])
def put_vault(body: VaultIn, _: dict = Depends(auth.require_user)):
    store.put_vault(_["id"], body.id, body.ciphertext)
    return {"ok": True}


@app.get("/api/vault/{vid}")
def get_vault(vid: str, _: dict = Depends(auth.require_user)):
    blob = store.get_vault(_["id"], vid)
    if blob is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {"id": vid, "ciphertext": blob}


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    daily_requests: int = Field(default=200, ge=1, le=1_000_000)
    daily_tokens: int = Field(default=500_000, ge=1, le=100_000_000)


@app.post("/api/admin/keys", dependencies=[Depends(require_admin)])
def mint_key(body: KeyIn):
    return store.create_api_key(body.name, "", body.daily_requests, body.daily_tokens)


@app.get("/api/admin/keys", dependencies=[Depends(require_admin)])
def list_keys():
    return store.list_api_keys()


@app.delete("/api/admin/keys/{kid}", dependencies=[Depends(require_admin)])
def revoke_key(kid: str):
    if not store.delete_api_key(kid):
        raise HTTPException(status_code=404, detail="API key not found.")
    return {"ok": True}


@app.post(
    "/v1/chat/completions",
    dependencies=[Depends(limits.chat_limit), Depends(limits.chat_body)],
)
async def openai_chat(req: openai_compat.OAChatRequest, _: dict = Depends(auth.require_user)):
    if req.stream:
        async def event_generator():
            chars = 0
            async for chunk in openai_compat.stream_completion(req):
                if '"content":' in chunk:
                    payload = json.loads(chunk.removeprefix("data: ").strip())
                    chars += len(payload["choices"][0]["delta"].get("content") or "")
                yield chunk
            if chars:
                store.bump_quota(_["id"], requests=0, tokens=max(1, chars // 4))

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    data = await openai_compat.collect_completion(req)
    if "error" in data:
        raise HTTPException(status_code=502, detail=data["error"]["message"])
    text = data["choices"][0]["message"]["content"]
    store.bump_quota(_["id"], requests=0, tokens=max(1, len(text) // 4))
    return data


@app.get("/v1/models", dependencies=[Depends(limits.chat_limit)])
def openai_models(_: dict = Depends(auth.require_user)):
    models = [{"id": "axiom", "object": "model", "owned_by": "axiom"}]
    models.extend(
        {
            "id": f"{provider}/{model}",
            "object": "model",
            "owned_by": provider,
        }
        for provider, config in providers.PROVIDERS.items()
        for model in config["models"]
    )
    return {"object": "list", "data": models}
