"""Credential / secret leak detection (gitleaks-style signatures + entropy fallback)."""

from __future__ import annotations

import math
import re
from collections import Counter

from ..types import Action, CheckContext, CheckResult, Stage
from .base import Check, register

SIGNATURES: dict[str, re.Pattern[str]] = {
    "aws_access_key": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws_secret_key": re.compile(r"(?i)aws.{0,20}(secret|key).{0,20}['\"=:\s]([A-Za-z0-9/+=]{40})\b"),
    "github_token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "anthropic_key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "openai_key": re.compile(r"\bsk-(proj-)?[A-Za-z0-9_-]{32,}"),
    "slack_token": re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "stripe_key": re.compile(r"\b(sk|rk)_live_[0-9A-Za-z]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY( BLOCK)?-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "db_connection_string": re.compile(r"\b(postgres(ql)?|mysql|mongodb(\+srv)?|redis|amqp)://[^\s:/@]+:[^\s@]{3,}@[^\s]+"),
    "password_assignment": re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)\b\s*[:=]\s*['\"]?([^\s'\"]{8,})"),
}

_TOKEN = re.compile(r"[A-Za-z0-9+/_=-]{32,}")
_PLACEHOLDER = re.compile(r"(?i)(x{6,}|\*{6,}|<[^>]+>|your[_-]|example|placeholder|redacted|\.\.\.)")


def shannon_entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


@register
class Secrets(Check):
    name = "secrets"
    stages = frozenset({Stage.INPUT, Stage.CONTEXT, Stage.OUTPUT})
    default_action = Action.REDACT
    modifies = True

    async def run(self, text: str, ctx: CheckContext) -> CheckResult:
        spans: list[tuple[str, int, int]] = []
        for kind, rx in SIGNATURES.items():
            for m in rx.finditer(text):
                if _PLACEHOLDER.search(m.group()):
                    continue
                spans.append((kind, m.start(), m.end()))

        if self.params.get("entropy", True):
            min_h = float(self.params.get("min_entropy", 4.5))
            for m in _TOKEN.finditer(text):
                tok = m.group()
                has_mix = any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)
                if has_mix and shannon_entropy(tok) >= min_h and not any(
                    m.start() < e and m.end() > s for _, s, e in spans
                ):
                    spans.append(("high_entropy_string", m.start(), m.end()))

        if not spans:
            return self.result(False)
        spans.sort(key=lambda x: x[1])
        out, last = [], 0
        for kind, s, e in spans:
            if s < last:
                continue
            out += [text[last:s], f"<SECRET:{kind}>"]
            last = e
        out.append(text[last:])
        kinds = sorted({k for k, *_ in spans})
        return self.result(True, score=1.0, reason=f"found {', '.join(kinds)}", modified_text="".join(out),
                           details={"kinds": kinds, "count": len(spans)})
