"""Dependency-free async load generator (httpx). Locust alternative for CI and quick runs.

    uv run python bench/load.py --host http://localhost:8848 --concurrency 50 --duration 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
from run_eval import load_cases, pct  # noqa: E402

CASES = load_cases(ROOT / "evals/data/redteam.jsonl") + load_cases(ROOT / "evals/data/benign.jsonl")
INPUTS = [c["text"] for c in CASES if c["stage"] == "input"]
OUTPUTS = [c for c in CASES if c["stage"] == "output"]


def pick() -> tuple[str, str, dict]:
    r = random.random()
    if r < 0.43:
        return "chat", "/v1/chat", {"messages": [{"role": "user", "content": random.choice(INPUTS)}]}
    if r < 0.71:
        return "guard_input", "/v1/guard/input", {"text": random.choice(INPUTS)}
    c = random.choice(OUTPUTS)
    return "guard_output", "/v1/guard/output", {"text": c["text"], "context": c.get("context", []),
                                                "response_schema": c.get("schema"), "user_input": c.get("user_input")}


async def worker(client: httpx.AsyncClient, deadline: float, lat: dict, errors: dict) -> None:
    while time.perf_counter() < deadline:
        name, path, body = pick()
        t0 = time.perf_counter()
        try:
            r = await client.post(path, json=body)
            if r.status_code != 200:
                errors[name] += 1
        except httpx.HTTPError:
            errors[name] += 1
        lat[name].append((time.perf_counter() - t0) * 1000)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://localhost:8848")
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--out", default=str(ROOT / "reports" / "load.json"))
    args = ap.parse_args()

    lat: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    limits = httpx.Limits(max_connections=args.concurrency)
    async with httpx.AsyncClient(base_url=args.host, limits=limits, timeout=30) as client:
        await client.get("/healthz")
        t0 = time.perf_counter()
        deadline = t0 + args.duration
        await asyncio.gather(*(worker(client, deadline, lat, errors) for _ in range(args.concurrency)))
        wall = time.perf_counter() - t0

    every = [x for xs in lat.values() for x in xs]
    report = {"concurrency": args.concurrency, "duration_s": round(wall, 1), "requests": len(every),
              "rps": round(len(every) / wall, 1), "errors": sum(errors.values()),
              "all": {"p50": round(pct(every, .5), 2), "p95": round(pct(every, .95), 2), "p99": round(pct(every, .99), 2)},
              "by_endpoint": {k: {"n": len(v), "p50": round(pct(v, .5), 2), "p99": round(pct(v, .99), 2),
                                  "errors": errors[k]} for k, v in sorted(lat.items())}}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
