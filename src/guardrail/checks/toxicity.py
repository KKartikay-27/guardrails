"""Toxicity: lexical signatures by default, detoxify model when the `ml` extra is installed."""

from __future__ import annotations

import re
from functools import lru_cache

from ..types import CheckContext, CheckResult, Stage
from .base import Check, normalize, register

# Deliberately conservative: targeted insults, threats, self-harm encouragement, harassment.
# Generic profanity alone is not blocked (support users swear at broken software).
LEXICON: dict[str, tuple[re.Pattern[str], float]] = {
    "threat": (re.compile(r"\b(i('| wi)ll|we('| wi)ll|gonna|going to)\s+(kill|hurt|find|destroy|shoot|stab|beat)\s+(you|u|your)\b"), 0.9),
    "self_harm_encouragement": (re.compile(r"\b(kill|hurt|harm) (yo)?urself\b|\bkys\b|\b(you should|go) (die|end it)\b"), 0.95),
    "targeted_insult": (re.compile(
        r"\byou(\s+are|'re|\s+r)?\s+(such\s+an?\s+|an?\s+|so\s+)?(fucking\s+|absolute\s+|complete\s+|total\s+)?"
        r"(idiot|moron|stupid|dumb|retard(ed)?|worthless|pathetic|useless piece|loser|imbecile|scum|trash|garbage)\b"), 0.75),
    "dehumanizing": (re.compile(r"\b(people like you|your (kind|people)|those people)\b.{0,40}\b(vermin|animals|subhuman|parasites|should (all )?(die|be (shot|killed|gassed)))\b"), 0.95),
    "harassment": (re.compile(r"\b(shut (the fuck )?up|nobody (cares|asked)|go to hell|screw you|fuck (you|off))\b"), 0.6),
}


@lru_cache(maxsize=1)
def _detoxify():  # pragma: no cover - only with the `ml` extra
    from detoxify import Detoxify

    return Detoxify("original-small")


@register
class Toxicity(Check):
    name = "toxicity"
    stages = frozenset({Stage.INPUT, Stage.OUTPUT})

    async def run(self, text: str, ctx: CheckContext) -> CheckResult:
        threshold = float(self.params.get("threshold", 0.6))
        t = normalize(text, leet=True)
        hits = {k: w for k, (rx, w) in LEXICON.items() if rx.search(t)}
        score = max(hits.values(), default=0.0)
        details: dict = {"categories": sorted(hits)}
        if self.params.get("model") == "detoxify":
            try:
                probs = _detoxify().predict(text[:2000])
                details["detoxify"] = {k: round(float(v), 3) for k, v in probs.items()}
                score = max(score, float(probs["toxicity"]))
            except ImportError:
                details["detoxify"] = "unavailable (install the `ml` extra)"
        return self.result(score >= threshold, score=round(score, 3),
                           reason=", ".join(sorted(hits)), details=details)
