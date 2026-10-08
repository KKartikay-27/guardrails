"""PII detection with reversible redaction.

Regex recognizers backed by checksum validation (Luhn for cards, mod-97 for IBAN,
Verhoeff for Aadhaar) to keep false positives down. Redaction swaps each value for a
stable placeholder like <EMAIL_1>; the mapping stays in memory for the request only so
the server can restore values in the model's reply if the policy allows it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ..types import Action, CheckContext, CheckResult, Stage
from .base import Check, register


def _luhn(s: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    return total % 10 == 0


def _iban(s: str) -> bool:
    s = s.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


_VD = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],
       [4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],
       [8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]  # fmt: skip
_VP = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
       [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]  # fmt: skip


def _verhoeff(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if len(digits) != 12 or digits[0] in "01":
        return False
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VD[c][_VP[i % 8][int(d)]]
    return c == 0


def _ssn(s: str) -> bool:
    area, group, serial = s.split("-")
    return area not in ("000", "666") and area[0] != "9" and group != "00" and serial != "0000"


def _ip(s: str) -> bool:
    parts = s.split(".")
    return all(0 <= int(p) <= 255 for p in parts) and s not in ("0.0.0.0", "127.0.0.1")


RECOGNIZERS: dict[str, tuple[re.Pattern[str], Callable[[str], bool] | None]] = {
    "EMAIL": (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    "CREDIT_CARD": (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), _luhn),
    "IBAN": (re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b"), _iban),
    "US_SSN": (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), _ssn),
    "IN_AADHAAR": (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"), _verhoeff),
    "IN_PAN": (re.compile(r"\b[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]\b"), None),
    "PHONE": (
        re.compile(r"(?<![\w.])(?<!\d[ .-])(?:\+?\d{1,3}[ .-]?)?(?:\(\d{2,4}\)[ .-]?|\d{2,4}[ .-])\d{3,4}[ .-]?\d{3,4}(?![\w.])(?![ .-]?\d)"),
        lambda s: 10 <= len(re.sub(r"\D", "", s)) <= 13,
    ),
    "IP_ADDRESS": (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), _ip),
}

# Order matters: card/IBAN/ID numbers before PHONE so long digit runs get the specific label.
ORDER = ["EMAIL", "CREDIT_CARD", "IBAN", "US_SSN", "IN_AADHAAR", "IN_PAN", "IP_ADDRESS", "PHONE"]


def find_pii(text: str, entities: list[str] | None = None, allow: set[str] | None = None) -> list[tuple[str, int, int, str]]:
    allow = {a.lower() for a in (allow or set())}
    taken: list[tuple[int, int]] = []
    found: list[tuple[str, int, int, str]] = []
    for label in ORDER:
        if entities and label not in entities:
            continue
        rx, validate = RECOGNIZERS[label]
        for m in rx.finditer(text):
            s, e, val = m.start(), m.end(), m.group()
            if val.lower() in allow or any(s < te and e > ts for ts, te in taken):
                continue
            if validate and not validate(val):
                continue
            taken.append((s, e))
            found.append((label, s, e, val))
    return sorted(found, key=lambda x: x[1])


def redact(text: str, spans: list[tuple[str, int, int, str]]) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    by_value: dict[str, str] = {}
    counts: dict[str, int] = {}
    out, last = [], 0
    for label, s, e, val in spans:
        if val not in by_value:
            counts[label] = counts.get(label, 0) + 1
            by_value[val] = f"<{label}_{counts[label]}>"
            mapping[by_value[val]] = val
        out += [text[last:s], by_value[val]]
        last = e
    out.append(text[last:])
    return "".join(out), mapping


@register
class PII(Check):
    name = "pii"
    stages = frozenset({Stage.INPUT, Stage.CONTEXT, Stage.OUTPUT})
    default_action = Action.REDACT
    modifies = True

    async def run(self, text: str, ctx: CheckContext) -> CheckResult:
        allow = set(self.params.get("allow_values", []))
        if ctx.stage == Stage.OUTPUT and self.params.get("ignore_echoed", True) and ctx.user_input:
            # PII the user supplied themselves isn't a leak when echoed back.
            allow |= {v for *_, v in find_pii(ctx.user_input)}
        spans = find_pii(text, self.params.get("entities"), allow)
        if not spans:
            return self.result(False)
        redacted, mapping = redact(text, spans)
        labels = sorted({s[0] for s in spans})
        return self.result(
            True,
            score=1.0,
            reason=f"found {', '.join(labels)}",
            modified_text=redacted,
            details={"entities": [{"type": s[0], "start": s[1], "end": s[2]} for s in spans], "_mapping": mapping},
        )
