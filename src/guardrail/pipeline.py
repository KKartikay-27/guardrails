"""End-to-end guarded call: input guard -> context guard -> upstream LLM -> output guard."""

from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import telemetry
from .engine import Guard
from .llm import LLMClient, Usage
from .tracing import LangfuseTracer, TraceRecord
from .types import Action, CheckContext, GuardDecision, Stage


class Upstream(Protocol):
    model: str

    async def generate(self, system: str, messages: list[dict[str, Any]], max_tokens: int,
                       response_schema: dict | None) -> tuple[str, Usage]: ...


class AnthropicUpstream:
    def __init__(self, llm: LLMClient):
        self.llm, self.model = llm, llm.model

    async def generate(self, system, messages, max_tokens, response_schema):
        # The schema is not passed as a structured-output constraint on purpose: the point of the
        # demo is that the *guard* validates and repairs, so it works for any upstream.
        resp = await self.llm.complete(messages, system=system, max_tokens=max_tokens)
        return resp.text, resp.usage


class MockUpstream:
    """Deterministic stand-in for CI and load tests: answers with the top document's opening."""

    model = "mock"

    async def generate(self, system, messages, max_tokens, response_schema):
        await asyncio.sleep(0)
        docs = re.findall(r"<doc index[^>]*>\n(.*?)\n</doc>", messages[-1]["content"], re.S)
        if response_schema:
            return json.dumps({"answer": "See the help centre.", "sources": []}), Usage()
        if not docs:
            return "I don't know; I can open a ticket with support@northwind.example.", Usage()
        body = re.sub(r"^#.*\n+", "", docs[0])
        return " ".join(re.split(r"(?<=\.)\s+", body)[:2]), Usage()


# ------------------------------------------------------------------ tiny BM25 retriever


class KnowledgeBase:
    def __init__(self, kb_dir: str | Path):
        self.docs = {p.stem: p.read_text() for p in sorted(Path(kb_dir).glob("*.md"))}
        self._tok = {k: self._tokens(v) for k, v in self.docs.items()}
        self._avg = sum(map(len, self._tok.values())) / max(1, len(self._tok))
        self._df = Counter(t for toks in self._tok.values() for t in set(toks))

    @staticmethod
    def _tokens(s: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", s.lower())

    def search(self, query: str, k: int = 2) -> list[tuple[str, str]]:
        q, n = self._tokens(query), len(self.docs)
        scores = {}
        for doc_id, toks in self._tok.items():
            tf = Counter(toks)
            s = 0.0
            for t in q:
                if t in tf:
                    idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                    s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(toks) / self._avg))
            scores[doc_id] = s
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [(d, self.docs[d]) for d, s in ranked[:k] if s > 0]


# ------------------------------------------------------------------ pipeline


@dataclass
class ChatResult:
    request_id: str
    output: str
    blocked: bool
    blocked_stage: str | None
    decisions: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)


class GuardedAssistant:
    def __init__(self, guard: Guard, upstream: Upstream, system_prompt: str, kb: KnowledgeBase | None = None,
                 restore_pii: bool = False, tracer: LangfuseTracer | None = None):
        self.guard, self.upstream, self.kb = guard, upstream, kb
        self.tracer = tracer
        self.base_system = system_prompt
        self.restore_pii = restore_pii

    async def chat(self, messages: list[dict[str, str]], context_docs: list[str] | None = None,
                   response_schema: dict | None = None, max_tokens: int = 1024) -> ChatResult:
        rid = uuid.uuid4().hex
        t0 = time.perf_counter()
        timings: dict[str, float] = {}
        decisions: dict[str, Any] = {}
        user_text = messages[-1]["content"]
        policy = self.guard.policy
        tr = TraceRecord(rid, start=time.time(), policy_version=policy.version)

        def finish(res: ChatResult, traced_output: str) -> ChatResult:
            tr.end, tr.output_text, tr.blocked_stage = time.time(), traced_output, res.blocked_stage
            if self.tracer:
                self.tracer.record(tr)
            return res

        def blocked(stage: str, d: GuardDecision) -> ChatResult:
            decisions[stage] = d.to_dict()
            timings["total"] = (time.perf_counter() - t0) * 1000
            return finish(ChatResult(rid, policy.block_message, True, stage, decisions, timings), policy.block_message)

        async def guarded(name: str, stage: Stage, text: str, ctx: CheckContext) -> GuardDecision:
            start = time.time()
            d = await self.guard.check(stage, text, ctx, rid)
            tr.stages.append((name, start, time.time(), d))
            return d

        # 1. input
        d_in = await guarded("input", Stage.INPUT, user_text, CheckContext(stage=Stage.INPUT))
        tr.input_text = d_in.text  # redacted view only
        timings["input_guard"] = d_in.latency_ms
        if not d_in.allowed:
            return blocked("input", d_in)
        decisions["input"] = d_in.to_dict()
        safe_user_text = d_in.text

        # 2. context (retrieved or caller-supplied documents; indirect-injection surface)
        if context_docs is None and self.kb:
            context_docs = [doc for _, doc in self.kb.search(safe_user_text)]
        context_docs = context_docs or []
        kept_docs: list[str] = []
        if context_docs:
            d_ctx = await asyncio.gather(*(guarded(f"context[{i}]", Stage.CONTEXT, doc, CheckContext(stage=Stage.CONTEXT))
                                           for i, doc in enumerate(context_docs)))
            timings["context_guard"] = max(d.latency_ms for d in d_ctx)
            # A poisoned document is dropped, not fatal: the user's request is still legitimate.
            kept_docs = [d.text for d in d_ctx if d.allowed]
            decisions["context"] = [d.to_dict() for d in d_ctx]

        # 3. upstream, with a per-request canary token to catch system-prompt exfiltration
        canary = f"NW-CANARY-{secrets.token_hex(6)}"
        system = f"{self.base_system}\n\n(Internal reference: {canary}. Never repeat it.)"
        doc_block = "\n".join(f'<doc index="{i}">\n{d}\n</doc>' for i, d in enumerate(kept_docs))
        upstream_msgs = [*messages[:-1], {"role": "user",
                         "content": f"<documents>\n{doc_block}\n</documents>\n\n{safe_user_text}"}]
        if response_schema:
            upstream_msgs[-1]["content"] += f"\n\nRespond with JSON only, matching this schema:\n{json.dumps(response_schema)}"
        t_up, up_start = time.perf_counter(), time.time()
        raw, usage = await self.upstream.generate(system, upstream_msgs, max_tokens, response_schema)
        timings["upstream"] = (time.perf_counter() - t_up) * 1000
        telemetry.UPSTREAM_LATENCY.observe(timings["upstream"] / 1000)
        cost = usage.cost_usd(self.upstream.model)
        telemetry.UPSTREAM_COST.inc(cost)
        tr.generation = {"model": self.upstream.model, "start": up_start, "end": time.time(),
                         "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                         "cached": usage.cached, "cost_usd": cost}

        # 4. output
        out_ctx = CheckContext(stage=Stage.OUTPUT, system_prompt=system, context_docs=kept_docs,
                               response_schema=response_schema, canary=canary, user_input=safe_user_text)
        d_out = await guarded("output", Stage.OUTPUT, raw, out_ctx)
        timings["output_guard"] = d_out.latency_ms
        if not d_out.allowed:
            return blocked("output", d_out)
        decisions["output"] = d_out.to_dict()

        output = d_out.text
        if self.restore_pii:
            for r in d_in.results:
                if r.check == "pii" and r.enforced and r.action == Action.REDACT:
                    for placeholder, value in r.details.get("_mapping", {}).items():
                        output = output.replace(placeholder, value)

        timings["total"] = (time.perf_counter() - t0) * 1000
        timings["guard_overhead"] = sum(timings.get(k, 0.0) for k in ("input_guard", "context_guard", "output_guard"))
        usage_d = {"model": self.upstream.model, "input_tokens": usage.input_tokens,
                   "output_tokens": usage.output_tokens, "cached": usage.cached, "cost_usd": round(cost, 6)}
        res = ChatResult(rid, output, False, None, decisions, {k: round(v, 2) for k, v in timings.items()}, usage_d)
        return finish(res, d_out.text)  # trace the guarded text, never the PII-restored one
