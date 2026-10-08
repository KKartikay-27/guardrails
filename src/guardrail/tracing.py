"""Langfuse tracing via the public ingestion API (no SDK dependency).

Enabled when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set. Each /v1/chat request becomes one
trace: a span per guard stage, a child span per check (WARNING level when it fired), a generation
for the upstream call with token usage, and a `guard_blocked` score. Only *guarded* text is sent
(PII and secrets already redacted); set GUARD_TRACE_CONTENT=none to send no text at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from .types import GuardDecision

log = logging.getLogger("guardrail.tracing")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


@dataclass
class TraceRecord:
    request_id: str
    start: float
    end: float = 0.0
    input_text: str | None = None
    output_text: str | None = None
    blocked_stage: str | None = None
    policy_version: str = ""
    stages: list[tuple[str, float, float, GuardDecision]] = field(default_factory=list)
    generation: dict[str, Any] | None = None


class LangfuseTracer:
    def __init__(self, host: str | None = None, public_key: str | None = None, secret_key: str | None = None,
                 flush_interval: float = 2.0, max_batch: int = 100, client: httpx.AsyncClient | None = None):
        self.public_key = public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        self.secret_key = secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        self.host = (host or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")).rstrip("/")
        self.send_content = os.getenv("GUARD_TRACE_CONTENT", "redacted") != "none"
        self.flush_interval, self.max_batch = flush_interval, max_batch
        self._buf: list[dict[str, Any]] = []
        self._task: asyncio.Task | None = None
        self._client = client
        self.sent = self.failed = 0

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.secret_key)

    # ------------------------------------------------------------------ event building

    @staticmethod
    def _event(kind: str, body: dict[str, Any], ts: float) -> dict[str, Any]:
        return {"id": uuid.uuid4().hex, "timestamp": _iso(ts), "type": kind, "body": body}

    def events_for(self, rec: TraceRecord) -> list[dict[str, Any]]:
        tid = rec.request_id
        content = self.send_content
        ev = [self._event("trace-create", {
            "id": tid,
            "name": "guarded-chat",
            "timestamp": _iso(rec.start),
            "input": rec.input_text if content else None,
            "output": rec.output_text if content else None,
            "release": rec.policy_version,
            "tags": ["blocked" if rec.blocked_stage else "allowed"]
                    + ([f"blocked:{rec.blocked_stage}"] if rec.blocked_stage else []),
            "metadata": {"policy_version": rec.policy_version},
        }, rec.start)]
        for name, t0, t1, d in rec.stages:
            sid = uuid.uuid4().hex
            ev.append(self._event("span-create", {
                "id": sid, "traceId": tid, "name": f"guard:{name}", "startTime": _iso(t0), "endTime": _iso(t1),
                "level": "WARNING" if d.action.value != "allow" else "DEFAULT",
                "statusMessage": ", ".join(d.blocked_by) or None,
                "metadata": {"action": d.action.value, "latency_ms": round(d.latency_ms, 3),
                             "shadow_hits": d.shadow_hits},
            }, t0))
            for r in d.results:
                if r.skipped:
                    continue
                ev.append(self._event("span-create", {
                    "id": uuid.uuid4().hex, "traceId": tid, "parentObservationId": sid,
                    "name": f"check:{r.policy_id}", "startTime": _iso(t0), "endTime": _iso(t0 + r.latency_ms / 1000),
                    "level": "ERROR" if r.error else "WARNING" if r.triggered else "DEBUG",
                    "statusMessage": r.error or r.reason or None,
                    "metadata": {"check": r.check, "mode": r.mode.value, "blocking": r.blocking,
                                 "triggered": r.triggered, "action": r.action.value, "score": r.score},
                }, t0))
        if g := rec.generation:
            ev.append(self._event("generation-create", {
                "id": uuid.uuid4().hex, "traceId": tid, "name": "upstream", "model": g["model"],
                "startTime": _iso(g["start"]), "endTime": _iso(g["end"]),
                "usage": {"input": g["input_tokens"], "output": g["output_tokens"], "unit": "TOKENS"},
                "metadata": {"cached": g["cached"], "cost_usd": g["cost_usd"]},
            }, g["start"]))
        ev.append(self._event("score-create", {
            "id": uuid.uuid4().hex, "traceId": tid, "name": "guard_blocked",
            "value": 1 if rec.blocked_stage else 0, "comment": rec.blocked_stage,
        }, rec.end or rec.start))
        return ev

    # ------------------------------------------------------------------ transport

    def record(self, rec: TraceRecord) -> None:
        if not self.enabled:
            return
        self._buf.extend(self.events_for(rec))
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self) -> None:
        while self._buf:
            await asyncio.sleep(self.flush_interval)
            await self.flush()

    async def flush(self) -> None:
        if not self._buf:
            return
        self._client = self._client or httpx.AsyncClient(timeout=10, auth=(self.public_key, self.secret_key))
        while self._buf:
            batch, self._buf = self._buf[: self.max_batch], self._buf[self.max_batch:]
            try:
                r = await self._client.post(f"{self.host}/api/public/ingestion", json={"batch": batch})
                if r.status_code >= 400:
                    raise httpx.HTTPStatusError(r.text[:200], request=r.request, response=r)
                self.sent += len(batch)
            except httpx.HTTPError as e:  # tracing must never break serving
                self.failed += len(batch)
                log.warning("langfuse ingestion failed: %s", e)

    async def aclose(self) -> None:
        await self.flush()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._client:
            await self._client.aclose()
