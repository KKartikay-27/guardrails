"""Topic allow/deny.

Each topic is a list of phrase patterns. Deny topics block when matched. If `allow`
topics are configured with `strict: true`, messages that match none of them are blocked
too (off by default: strict allow-lists are where false positives come from).
"""

from __future__ import annotations

import re

from ..types import CheckContext, CheckResult, Stage
from .base import Check, normalize, register

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"topic": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["topic", "reason"],
    "additionalProperties": False,
}


def _compile(topics: dict[str, list[str]]) -> dict[str, list[re.Pattern[str]]]:
    return {t: [re.compile(rf"\b{p}\b", re.I) for p in pats] for t, pats in topics.items()}


@register
class Topic(Check):
    name = "topic"
    stages = frozenset({Stage.INPUT, Stage.OUTPUT})

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.deny = _compile(self.params.get("deny", {}))
        self.allow = _compile(self.params.get("allow", {}))

    async def run(self, text: str, ctx: CheckContext) -> CheckResult:
        t = normalize(text)
        denied = sorted(topic for topic, pats in self.deny.items() if any(p.search(t) for p in pats))
        allowed = sorted(topic for topic, pats in self.allow.items() if any(p.search(t) for p in pats))

        if self.params.get("method") == "llm" and self.llm:
            labels = list(self.deny) + list(self.allow) + ["other"]
            verdict = await self.llm.judge(
                system="Classify the user's message into exactly one topic label. "
                       f"Labels: {', '.join(labels)}. Use 'other' if none fit.",
                prompt=f"<message>\n{text[:4000]}\n</message>",
                schema=_JUDGE_SCHEMA,
                max_tokens=200,
            )
            denied = [verdict["topic"]] if verdict["topic"] in self.deny else []
            allowed = [verdict["topic"]] if verdict["topic"] in self.allow else allowed

        off_topic = bool(self.params.get("strict") and self.allow and not allowed)
        triggered = bool(denied) or off_topic
        reason = f"denied topic: {', '.join(denied)}" if denied else ("off-topic" if off_topic else "")
        return self.result(triggered, score=1.0 if triggered else 0.0, reason=reason,
                           details={"denied": denied, "allowed": allowed})
