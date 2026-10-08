"""Reproduce the CI gate catching a bad policy change, locally.

    uv run python evals/regression_demo.py

Applies a plausible-looking edit to policies/default.yaml (raise the injection threshold from 0.5
to 0.9 "to cut false positives"), re-runs the suite, and compares against evals/baseline.json
exactly as CI does. Exits with the gate's status, so a passing gate here means the gate is broken.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
policy = (ROOT / "policies" / "default.yaml").read_text()
old = "    params:\n      threshold: 0.5\n"
assert old in policy, "default policy no longer has the injection threshold this demo edits"
weak = policy.replace(old, "    params:\n      threshold: 0.9\n", 1).replace('version: "', 'version: "regression-demo-', 1)

with tempfile.TemporaryDirectory() as d:
    p, report = Path(d) / "policy.yaml", Path(d) / "eval.json"
    p.write_text(weak)
    subprocess.run([sys.executable, str(ROOT / "evals/run_eval.py"), "--policy", str(p), "--out", str(report)],
                   check=True, stdout=subprocess.DEVNULL)
    gate = subprocess.run([sys.executable, str(ROOT / "evals/compare.py"), str(report),
                           str(ROOT / "evals/baseline.json"), "--md", str(ROOT / "reports/regression_demo.md")])
print(f"\ngate exit code: {gate.returncode} ({'blocked, as expected' if gate.returncode else 'PASSED: gate is broken'})")
sys.exit(0 if gate.returncode else 1)
