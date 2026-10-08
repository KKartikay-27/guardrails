"""HTTP surface.

POST /v1/chat            full guarded round-trip against the configured upstream
POST /v1/guard/{stage}   run one stage only, so the layer can wrap any endpoint you already have
GET  /v1/policy          active policy (version, checks, modes)
GET  /metrics            Prometheus
GET  /                   playground
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from .engine import Guard
from .llm import LLMClient
from .pipeline import AnthropicUpstream, GuardedAssistant, KnowledgeBase, MockUpstream
from .policy import load_policy
from .tracing import LangfuseTracer
from .types import CheckContext, Stage

ROOT = Path(os.getenv("GUARD_ROOT", Path(__file__).resolve().parents[2]))
POLICY_PATH = os.getenv("GUARD_POLICY", str(ROOT / "policies" / "default.yaml"))
UPSTREAM = os.getenv("GUARD_UPSTREAM", "anthropic" if LLMClient.available() else "mock")


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=32_000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    context: list[str] | None = Field(None, description="Override retrieval with your own documents")
    response_schema: dict[str, Any] | None = None
    max_tokens: int = Field(1024, le=4096)


class GuardRequest(BaseModel):
    text: str = Field(max_length=64_000)
    system_prompt: str | None = None
    context: list[str] = Field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    user_input: str | None = None


def build_app() -> FastAPI:
    policy = load_policy(POLICY_PATH)
    llm = LLMClient() if LLMClient.available() else None
    guard = Guard(policy, llm=llm)
    tracer = LangfuseTracer()
    upstream = AnthropicUpstream(llm) if UPSTREAM == "anthropic" and llm else MockUpstream()
    assistant = GuardedAssistant(
        guard, upstream,
        system_prompt=(ROOT / "product" / "system_prompt.md").read_text(),
        kb=KnowledgeBase(ROOT / "product" / "kb"),
        tracer=tracer,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await guard.drain()
        await tracer.aclose()
        guard.log.close()

    app = FastAPI(title="Guardrail", version=policy.version, lifespan=lifespan)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "policy_version": policy.version, "upstream": upstream.model, "llm_judge": llm is not None,
                "tracing": tracer.enabled}

    @app.get("/v1/policy")
    async def get_policy():
        return policy.model_dump(mode="json") | {"fingerprint": policy.fingerprint}

    @app.post("/v1/chat")
    async def chat(req: ChatRequest):
        if req.messages[-1].role != "user":
            raise HTTPException(400, "last message must be from the user")
        res = await assistant.chat([m.model_dump() for m in req.messages], req.context, req.response_schema,
                                   req.max_tokens)
        return res.__dict__

    @app.post("/v1/guard/{stage}")
    async def guard_stage(stage: Stage, req: GuardRequest):
        ctx = CheckContext(stage=stage, system_prompt=req.system_prompt, context_docs=req.context,
                           response_schema=req.response_schema, user_input=req.user_input)
        d = await guard.check(stage, req.text, ctx)
        return d.to_dict() | {"text": d.text}

    @app.get("/metrics")
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/")
    async def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    return app


app = build_app()
