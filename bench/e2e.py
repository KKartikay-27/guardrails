"""End-to-end latency budget and cost per request against the real upstream (Claude Haiku).

    uv run --env-file .env python bench/e2e.py --n 30

Sends the benign support questions from the eval set through the full guarded pipeline under three
profiles, with the response cache disabled so every number is a real API call:

  patterns-only      default.yaml, no judge: what the guard costs with zero LLM calls
  llm-blocking       llm-assisted.yaml: Haiku judge on inputs / context docs, grounding judge inline
  llm-async-ground   llm-assisted.yaml with the grounding check moved off the critical path

Reports guard overhead vs. upstream latency (p50/p99), judge calls per request, $ per request, and
how many of these legitimate questions each profile wrongly blocked.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from run_eval import load_cases, pct  # noqa: E402

from guardrail.engine import Guard  # noqa: E402
from guardrail.llm import LLMClient  # noqa: E402
from guardrail.pipeline import AnthropicUpstream, GuardedAssistant, KnowledgeBase  # noqa: E402
from guardrail.policy import load_policy  # noqa: E402
from guardrail.telemetry import DecisionLog  # noqa: E402


def profile(name: str):
    if name == "patterns-only":
        return load_policy(ROOT / "policies/default.yaml"), False
    p = load_policy(ROOT / "policies/llm-assisted.yaml")
    if name == "llm-async-ground":
        for _, cp in p.all_checks():
            if cp.id == "grounding":
                cp.blocking = False
    return p, True


async def run_profile(name: str, questions: list[str], concurrency: int) -> dict:
    policy, use_judge = profile(name)
    judge = LLMClient(cache_dir="") if use_judge else None
    upstream_llm = LLMClient(cache_dir="")
    guard = Guard(policy, llm=judge, log=DecisionLog(""))
    bot = GuardedAssistant(guard, AnthropicUpstream(upstream_llm),
                           (ROOT / "product/system_prompt.md").read_text(), KnowledgeBase(ROOT / "product/kb"))
    sem = asyncio.Semaphore(concurrency)

    async def one(q: str):
        async with sem:
            return await bot.chat([{"role": "user", "content": q}], max_tokens=400)

    results = await asyncio.gather(*(one(q) for q in questions))
    await guard.drain()

    def s(xs):
        return {"p50": round(pct(xs, .5), 1), "p99": round(pct(xs, .99), 1)}

    answered = [r for r in results if not r.blocked]
    n = len(results)
    judge_calls = judge.calls if judge else 0
    judge_usd = judge.spent_usd if judge else 0.0
    return {
        "profile": name,
        "policy_version": policy.version,
        "requests": n,
        "wrongly_blocked": [(r.blocked_stage, q) for r, q in zip(results, questions, strict=True) if r.blocked],
        "guard_overhead_ms": s([r.timings_ms.get("guard_overhead", r.timings_ms.get("total", 0)) for r in results]),
        "upstream_ms": s([r.timings_ms["upstream"] for r in answered]),
        "total_ms": s([r.timings_ms["total"] for r in results]),
        "judge_calls_per_request": round(judge_calls / n, 2),
        "usd_per_request": {
            "upstream": round(upstream_llm.spent_usd / n, 6),
            "judge": round(judge_usd / n, 6),
            "total": round((upstream_llm.spent_usd + judge_usd) / n, 6),
        },
        "sample_answer": answered[0].output[:300] if answered else None,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--profiles", default="patterns-only,llm-blocking,llm-async-ground")
    ap.add_argument("--out", default=str(ROOT / "reports/e2e.json"))
    args = ap.parse_args()
    if not LLMClient.available():
        sys.exit("needs ANTHROPIC_API_KEY (put it in .env and run via `make bench-e2e`)")

    benign = [c["text"] for c in load_cases(ROOT / "evals/data/benign.jsonl") if c["stage"] == "input"]
    questions = (benign * (args.n // len(benign) + 1))[: args.n]
    report = {"n": args.n, "upstream_model": LLMClient().model, "profiles": []}
    for name in args.profiles.split(","):
        r = await run_profile(name, questions, args.concurrency)
        report["profiles"].append(r)
        print(f"{name:18} guard p50/p99 {r['guard_overhead_ms']['p50']:7.1f}/{r['guard_overhead_ms']['p99']:7.1f} ms  "
              f"upstream p50/p99 {r['upstream_ms']['p50']:7.1f}/{r['upstream_ms']['p99']:7.1f} ms  "
              f"judge/req {r['judge_calls_per_request']:.2f}  $/req {r['usd_per_request']['total']:.5f}  "
              f"wrongly blocked {len(r['wrongly_blocked'])}/{r['requests']}")
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
