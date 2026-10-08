"""The guard engine: runs a policy's checks for one stage and folds them into a decision.

Execution model per stage:
  * blocking detectors run concurrently on the original text
  * blocking modifiers (redact / repair) run sequentially, each on the previous one's output,
    concurrently with the detectors
  * non-blocking checks are fired as background tasks: they never add latency or change the
    decision, they only land in metrics and the decision log ("async" mode)
  * shadow-mode checks run inline but their verdicts are only recorded, never enforced
"""

from __future__ import annotations

import asyncio
import time
import uuid

from . import telemetry
from .checks import REGISTRY, Check
from .llm import LLMClient
from .policy import CheckPolicy, Policy
from .types import ACTION_SEVERITY, Action, CheckContext, CheckResult, GuardDecision, Mode, Stage


class Guard:
    def __init__(self, policy: Policy, llm: LLMClient | None = None, log: telemetry.DecisionLog | None = None):
        self.policy = policy
        self.llm = llm
        self.log = log if log is not None else telemetry.DecisionLog()
        self._background: set[asyncio.Task] = set()
        self.checks: dict[Stage, list[tuple[CheckPolicy, Check]]] = {s: [] for s in Stage}
        for stage, cp in policy.all_checks():
            if cp.check not in REGISTRY:
                raise ValueError(f"{cp.id}: unknown check type {cp.check!r}; known: {sorted(REGISTRY)}")
            cls = REGISTRY[cp.check]
            if stage not in cls.stages:
                raise ValueError(f"{cp.id}: check {cp.check!r} does not support stage {stage.value!r}")
            self.checks[stage].append((cp, cls(cp.id, cp.params, cp.action, llm)))

    async def _run_one(self, stage: Stage, cp: CheckPolicy, check: Check, text: str, ctx: CheckContext) -> CheckResult:
        t0 = time.perf_counter()
        try:
            r = await asyncio.wait_for(check.run(text, ctx), timeout=cp.timeout_ms / 1000)
        except Exception as e:  # includes TimeoutError: a slow check must not take the request down
            fail_closed = cp.on_error == "block"
            r = check.result(fail_closed, error=f"{type(e).__name__}: {e}"[:300],
                             reason="check failed; fail-closed" if fail_closed else "check failed; fail-open")
            if fail_closed:
                r.action = Action.BLOCK
        r.latency_ms = (time.perf_counter() - t0) * 1000
        r.mode, r.blocking = cp.mode, cp.blocking
        telemetry.record_check(stage.value, r)
        return r

    async def _run_background(self, stage, cp, check, text, ctx, request_id) -> None:
        r = await self._run_one(stage, cp, check, text, ctx)
        self.log.write("async_check", request_id, {"stage": stage.value, "policy_version": self.policy.version,
                                                     "result": r.to_dict()})

    async def check(self, stage: Stage, text: str, ctx: CheckContext | None = None,
                    request_id: str | None = None) -> GuardDecision:
        ctx = ctx or CheckContext(stage=stage)
        ctx.stage = stage
        request_id = request_id or uuid.uuid4().hex
        t0 = time.perf_counter()

        active = [(cp, c) for cp, c in self.checks[stage] if cp.mode != Mode.OFF]
        for cp, c in active:
            if not cp.blocking:
                task = asyncio.create_task(self._run_background(stage, cp, c, text, ctx, request_id))
                self._background.add(task)
                task.add_done_callback(self._background.discard)

        inline = [(cp, c) for cp, c in active if cp.blocking]
        detectors = [(cp, c) for cp, c in inline if not c.modifies]
        modifiers = [(cp, c) for cp, c in inline if c.modifies]

        async def run_modifiers() -> tuple[list[CheckResult], str]:
            current, out = text, []
            for cp, c in modifiers:
                r = await self._run_one(stage, cp, c, current, ctx)
                if r.enforced and r.modified_text is not None and r.action in (Action.REDACT, Action.REPAIR):
                    current = r.modified_text
                out.append(r)
            return out, current

        det_results, (mod_results, final_text) = await asyncio.gather(
            asyncio.gather(*(self._run_one(stage, cp, c, text, ctx) for cp, c in detectors)),
            run_modifiers(),
        )
        order = {cp.id: i for i, (cp, _) in enumerate(inline)}
        results = sorted([*det_results, *mod_results], key=lambda r: order[r.policy_id])

        enforced = [r for r in results if r.enforced]
        action = max((r.action for r in enforced), key=ACTION_SEVERITY.__getitem__, default=Action.ALLOW)
        decision = GuardDecision(
            stage=stage,
            action=action,
            text=final_text,
            results=results,
            policy_version=self.policy.version,
            latency_ms=(time.perf_counter() - t0) * 1000,
            blocked_by=[r.policy_id for r in enforced if r.action == Action.BLOCK],
            shadow_hits=[r.policy_id for r in results if r.triggered and r.mode == Mode.SHADOW],
        )
        telemetry.record_decision(decision)
        self.log.write("decision", request_id, decision.to_dict(), text=text)
        return decision

    async def check_many(self, stage: Stage, texts: list[str], ctx: CheckContext | None = None,
                         request_id: str | None = None) -> list[GuardDecision]:
        return list(await asyncio.gather(*(self.check(stage, t, ctx, request_id) for t in texts)))

    async def drain(self) -> None:
        """Wait for background (non-blocking) checks; used by evals, benchmarks and shutdown."""
        if self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)
