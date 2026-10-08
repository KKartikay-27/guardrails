"""Thin async wrapper around the Anthropic SDK with an on-disk response cache.

Used both as the upstream model and as the LLM judge for the checks that need one
(grounding, schema repair, optional injection gray-zone). The cache keys on the full
request so dev loops and eval reruns cost nothing after the first pass.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

DEFAULT_MODEL = os.getenv("GUARD_LLM_MODEL", "claude-haiku-4-5")

# USD per 1M tokens, used for the cost-per-request numbers in reports.
PRICING = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False

    def cost_usd(self, model: str) -> float:
        if self.cached:
            return 0.0
        inp, out = PRICING.get(model, (0.0, 0.0))
        return (self.input_tokens * inp + self.output_tokens * out) / 1_000_000


@dataclass
class LLMResponse:
    text: str
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None


class BudgetExceeded(RuntimeError):
    """Raised instead of calling the API once the persistent spend ledger reaches the cap."""


class SpendLedger:
    """Running total of real (uncached) API spend, persisted across runs so no script can drain the key.

    GUARD_LLM_BUDGET_USD sets the cap (default 2.00; 0 disables it). The ledger lives at
    GUARD_LLM_LEDGER (default .cache/llm_spend.json); delete it or raise the cap to reset.
    """

    def __init__(self, path: str | None = None, cap_usd: float | None = None):
        self.path = Path(path or os.getenv("GUARD_LLM_LEDGER", ".cache/llm_spend.json"))
        self.cap = float(cap_usd if cap_usd is not None else os.getenv("GUARD_LLM_BUDGET_USD", "2.00"))

    def total(self) -> float:
        try:
            return float(json.loads(self.path.read_text())["spent_usd"])
        except (FileNotFoundError, ValueError, KeyError):
            return 0.0

    def check(self) -> None:
        if self.cap > 0 and (spent := self.total()) >= self.cap:
            raise BudgetExceeded(f"LLM budget exhausted: ${spent:.2f} of ${self.cap:.2f} "
                                 "(raise GUARD_LLM_BUDGET_USD to continue)")

    def add(self, usd: float) -> None:
        if usd <= 0:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        total = self.total() + usd
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"spent_usd": round(total, 6), "cap_usd": self.cap}))
        tmp.replace(self.path)


class LLMClient:
    def __init__(self, model: str = DEFAULT_MODEL, cache_dir: str | None = None, timeout: float = 30.0,
                 ledger: SpendLedger | None = None):
        self.model = model
        self.ledger = ledger or SpendLedger()
        self._client = anthropic.AsyncAnthropic(timeout=timeout, max_retries=2)
        cache_dir = cache_dir if cache_dir is not None else os.getenv("GUARD_LLM_CACHE_DIR", ".cache/llm")
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls = self.cache_hits = 0
        self.spent_usd = 0.0

    @staticmethod
    def available() -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

    def _key(self, payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _cache_get(self, key: str) -> LLMResponse | None:
        if not self.cache_dir:
            return None
        p = self.cache_dir / f"{key}.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text())
        return LLMResponse(text=d["text"], usage=Usage(**d["usage"], cached=True), stop_reason=d["stop_reason"])

    def _cache_put(self, key: str, resp: LLMResponse) -> None:
        if not self.cache_dir:
            return
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps({"text": resp.text, "usage": usage, "stop_reason": resp.stop_reason})
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        max_tokens: int = 1024,
        output_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if system:
            payload["system"] = system
        if output_schema:
            payload["output_config"] = {"format": {"type": "json_schema", "schema": output_schema}}

        key = self._key(payload)
        self.calls += 1
        if (hit := self._cache_get(key)) is not None:
            self.cache_hits += 1
            return hit

        self.ledger.check()
        msg = await self._client.messages.create(**payload)
        text = "".join(b.text for b in msg.content if b.type == "text")
        resp = LLMResponse(
            text=text,
            usage=Usage(msg.usage.input_tokens, msg.usage.output_tokens),
            stop_reason=msg.stop_reason,
        )
        cost = resp.usage.cost_usd(self.model)
        self.spent_usd += cost
        self.ledger.add(cost)
        if msg.stop_reason not in ("refusal", "max_tokens"):
            self._cache_put(key, resp)
        return resp

    async def judge(self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 512) -> dict[str, Any]:
        """Single structured-output call; returns the parsed JSON object."""
        resp = await self.complete(
            [{"role": "user", "content": prompt}], system=system, max_tokens=max_tokens, output_schema=schema
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("judge refused")
        return json.loads(resp.text)
