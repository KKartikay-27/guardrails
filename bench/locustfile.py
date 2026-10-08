"""HTTP load test against a running server.

    GUARD_UPSTREAM=mock uv run uvicorn guardrail.server:app --port 8848 --workers 2
    uv run --extra load locust -f bench/locustfile.py --host http://localhost:8848 \
        --headless -u 50 -r 10 -t 60s --csv reports/locust

Use the mock upstream to measure the guard layer itself; with the real upstream, throughput is
bounded by the model API, not the guard.
"""

import random
import sys
from pathlib import Path

from locust import HttpUser, between, task

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
from run_eval import load_cases  # noqa: E402

DATA = ROOT / "evals" / "data"
CASES = load_cases(DATA / "redteam.jsonl") + load_cases(DATA / "benign.jsonl")
INPUTS = [c["text"] for c in CASES if c["stage"] == "input"]
OUTPUTS = [c for c in CASES if c["stage"] == "output"]


class GuardUser(HttpUser):
    wait_time = between(0.0, 0.05)

    @task(3)
    def chat(self):
        self.client.post("/v1/chat", json={"messages": [{"role": "user", "content": random.choice(INPUTS)}]},
                         name="/v1/chat")

    @task(2)
    def guard_input(self):
        self.client.post("/v1/guard/input", json={"text": random.choice(INPUTS)}, name="/v1/guard/input")

    @task(2)
    def guard_output(self):
        c = random.choice(OUTPUTS)
        self.client.post("/v1/guard/output", json={"text": c["text"], "context": c.get("context", []),
                                                   "response_schema": c.get("schema"),
                                                   "user_input": c.get("user_input")}, name="/v1/guard/output")
