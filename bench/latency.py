"""Guard overhead benchmark: blocking vs. async (non-blocking) execution of the slower checks.

    uv run python bench/latency.py --iters 20 --out reports/latency.json

Replays every eval case `iters` times through the guard and reports the latency the guard adds
to a request (p50 / p95 / p99 per stage), plus per-check cost. The `async` profile moves the
listed checks to background execution, which is how you'd run an LLM-judged check in production
without paying for it on the critical path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from run_eval import CANARY, SYSTEM_PROMPT, load_cases, pct  # noqa: E402

from guardrail.engine import Guard  # noqa: E402
from guardrail.llm import LLMClient  # noqa: E402
from guardrail.policy import Policy, load_policy  # noqa: E402
from guardrail.telemetry import DecisionLog  # noqa: E402
from guardrail.types import CheckContext, Mode, Stage  # noqa: E402


def make_profile(policy: Policy, async_ids: set[str]) -> Policy:
    p = policy.with_mode(Mode.ENFORCE)
    for _, cp in p.all_checks():
        if cp.id in async_ids:
            cp.blocking = False
    return p


async def bench(policy: Policy, cases: list[dict], iters: int, llm: LLMClient | None) -> dict:
    guard = Guard(policy, llm=llm, log=DecisionLog(""))
    by_stage: dict[str, list[float]] = {}
    by_check: dict[str, list[float]] = {}
    t0 = time.perf_counter()
    n = 0
    for _ in range(iters):
        for c in cases:
            stage = Stage(c["stage"])
            ctx = CheckContext(stage=stage, system_prompt=SYSTEM_PROMPT if stage == Stage.OUTPUT else None,
                               canary=CANARY, context_docs=c.get("context", []), response_schema=c.get("schema"),
                               user_input=c.get("user_input"))
            d = await guard.check(stage, c["text"].replace("{{CANARY}}", CANARY), ctx)
            by_stage.setdefault(stage.value, []).append(d.latency_ms)
            for r in d.results:
                if not r.skipped:
                    by_check.setdefault(r.policy_id, []).append(r.latency_ms)
            n += 1
    wall = time.perf_counter() - t0
    await guard.drain()

    def s(xs):
        return {"p50": round(pct(xs, .5), 3), "p95": round(pct(xs, .95), 3), "p99": round(pct(xs, .99), 3), "n": len(xs)}

    return {"by_stage_ms": {k: s(v) for k, v in sorted(by_stage.items())},
            "by_check_ms": {k: s(v) for k, v in sorted(by_check.items())},
            "sequential_checks_per_s": round(n / wall, 1)}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default=str(ROOT / "policies" / "default.yaml"))
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--llm", action="store_true", help="include LLM-judged paths (grounding hybrid, schema repair)")
    ap.add_argument("--async-checks", default="grounding,toxicity_output,toxicity_input",
                    help="policy ids moved to background execution in the `async` profile")
    ap.add_argument("--out", default=str(ROOT / "reports" / "latency.json"))
    args = ap.parse_args()

    policy = load_policy(args.policy)
    cases = load_cases(ROOT / "evals/data/redteam.jsonl") + load_cases(ROOT / "evals/data/benign.jsonl")
    llm = LLMClient() if args.llm and LLMClient.available() else None
    async_ids = set(filter(None, args.async_checks.split(",")))

    report = {"iters": args.iters, "cases": len(cases), "llm": llm.model if llm else None,
              "blocking": await bench(make_profile(policy, set()), cases, args.iters, llm),
              "async": await bench(make_profile(policy, async_ids), cases, args.iters, llm),
              "async_checks": sorted(async_ids)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))

    print(f"{'stage':8} {'profile':9} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8}")
    for stage in report["blocking"]["by_stage_ms"]:
        for prof in ("blocking", "async"):
            st = report[prof]["by_stage_ms"][stage]
            print(f"{stage:8} {prof:9} {st['p50']:8.3f} {st['p95']:8.3f} {st['p99']:8.3f}")
    print("\nper check (blocking profile):")
    for k, st in report["blocking"]["by_check_ms"].items():
        print(f"  {k:20} p50 {st['p50']:7.3f}  p99 {st['p99']:7.3f}")
    print(f"\nthroughput (single core, sequential): {report['blocking']['sequential_checks_per_s']} guard calls/s")


if __name__ == "__main__":
    asyncio.run(main())
