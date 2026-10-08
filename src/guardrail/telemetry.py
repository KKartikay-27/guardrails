"""Prometheus metrics + the JSONL decision log that powers shadow-mode analysis."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Histogram

from .types import CheckResult, GuardDecision

_LAT_BUCKETS = (0.0001, 0.00025, 0.0005, 0.00075, 0.001, 0.0015, 0.002, 0.003, 0.005, 0.0075, 0.01, 0.025,
                0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)

CHECK_OUTCOMES = Counter(
    "guardrail_check_total", "Check executions by outcome",
    ["policy_id", "stage", "mode", "outcome"],  # outcome: pass | trigger | skip | error
)
CHECK_LATENCY = Histogram("guardrail_check_latency_seconds", "Per-check latency", ["policy_id"], buckets=_LAT_BUCKETS)
STAGE_OVERHEAD = Histogram(
    "guardrail_stage_overhead_seconds", "Blocking latency added by a guard stage", ["stage"], buckets=_LAT_BUCKETS
)
DECISIONS = Counter("guardrail_decisions_total", "Stage decisions", ["stage", "action"])
SHADOW_HITS = Counter("guardrail_shadow_hits_total", "Would-have-acted events in shadow mode", ["policy_id"])
UPSTREAM_LATENCY = Histogram("guardrail_upstream_latency_seconds", "Upstream LLM latency", buckets=_LAT_BUCKETS)
UPSTREAM_COST = Counter("guardrail_upstream_cost_usd_total", "Upstream LLM spend (USD)")


def record_check(stage: str, r: CheckResult) -> None:
    outcome = "error" if r.error else "skip" if r.skipped else "trigger" if r.triggered else "pass"
    CHECK_OUTCOMES.labels(r.policy_id, stage, r.mode.value, outcome).inc()
    CHECK_LATENCY.labels(r.policy_id).observe(r.latency_ms / 1000)
    if r.triggered and not r.enforced:
        SHADOW_HITS.labels(r.policy_id).inc()


def record_decision(d: GuardDecision) -> None:
    STAGE_OVERHEAD.labels(d.stage.value).observe(d.latency_ms / 1000)
    DECISIONS.labels(d.stage.value, d.action.value).inc()


class DecisionLog:
    """Append-only JSONL. Never stores raw text: only a hash, so logs are safe to keep.

    Writes go through a queue drained by a daemon thread so file I/O never blocks the event loop.
    """

    def __init__(self, path: str | None = None):
        path = path if path is not None else os.getenv("GUARD_DECISION_LOG", "logs/decisions.jsonl")
        self.path = Path(path) if path else None
        self._q: queue.SimpleQueue[str | None] = queue.SimpleQueue()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._thread = threading.Thread(target=self._drain, daemon=True, name="decision-log")
            self._thread.start()

    def _drain(self) -> None:
        assert self.path is not None
        with open(self.path, "a", buffering=1) as f:
            while (line := self._q.get()) is not None:
                f.write(line + "\n")

    def write(self, kind: str, request_id: str, payload: dict[str, Any], text: str | None = None) -> None:
        if not self.path:
            return
        rec = {"ts": time.time(), "kind": kind, "request_id": request_id, **payload}
        if text is not None:
            rec["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()[:16]
        self._q.put(json.dumps(rec, default=str))

    def close(self) -> None:
        if self.path:
            self._q.put(None)
            self._thread.join(timeout=2)
