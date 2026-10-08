"""Credential-shaped fixtures should be generated locally, not stored in datasets."""

import json
import sys
from pathlib import Path

import pytest

from guardrail.checks.secrets import Secrets
from guardrail.types import Action, CheckContext, Stage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
from run_eval import load_cases  # noqa: E402


@pytest.mark.parametrize("marker,kind", [
    ("{{SYNTHETIC_STRIPE_KEY}}", "stripe_key"),
    ("{{SYNTHETIC_MONGODB_URI}}", "db_connection_string"),
])
async def test_generated_fixture_still_exercises_secret_detector(tmp_path, marker, kind):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"id": "fixture", "text": f"Leaked value: {marker}"}) + "\n")
    case = load_cases(path)[0]
    result = await Secrets("secrets", {}, Action.BLOCK, None).run(
        case["text"], CheckContext(stage=Stage.OUTPUT)
    )
    assert result.triggered
    assert kind in result.details["kinds"]
    assert result.action == Action.BLOCK
    assert case["id"] == "fixture"


@pytest.mark.parametrize("relative", ["evals/data/redteam.jsonl", "deliverables/evaluation/redteam.jsonl"])
def test_flagged_cases_store_only_named_fixtures(relative):
    cases = {c["id"]: c for c in [json.loads(line) for line in (ROOT / relative).read_text().splitlines()]}
    # Boolean assertions avoid printing a credential-shaped value on failure.
    assert bool("{{SYNTHETIC_MONGODB_URI}}" in cases["sleak-002"]["text"])
    assert bool("{{SYNTHETIC_STRIPE_KEY}}" in cases["sleak-003"]["text"])
