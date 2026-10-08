from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Stage(StrEnum):
    INPUT = "input"        # the user's message, before it reaches the model
    CONTEXT = "context"    # retrieved documents / tool results (indirect injection surface)
    OUTPUT = "output"      # the model's response, before it reaches the user


class Mode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"      # run and log what would have happened, never act
    ENFORCE = "enforce"


class Action(StrEnum):
    ALLOW = "allow"
    REDACT = "redact"      # replace offending spans, let the request continue
    REPAIR = "repair"      # fix the payload (e.g. malformed JSON), let it continue
    BLOCK = "block"


# Higher wins when several enforced checks disagree.
ACTION_SEVERITY = {Action.ALLOW: 0, Action.REPAIR: 1, Action.REDACT: 2, Action.BLOCK: 3}


@dataclass
class CheckContext:
    """Everything a check may need beyond the text it is inspecting."""

    stage: Stage
    system_prompt: str | None = None
    context_docs: list[str] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    canary: str | None = None
    user_input: str | None = None   # original user text, available to output checks


@dataclass
class CheckResult:
    policy_id: str
    check: str
    triggered: bool
    action: Action = Action.ALLOW          # what this check does when triggered and enforced
    score: float = 0.0
    reason: str = ""
    modified_text: str | None = None       # set by redact / repair checks
    details: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    mode: Mode = Mode.ENFORCE
    blocking: bool = True
    skipped: bool = False                  # check not applicable (e.g. no schema supplied)
    error: str | None = None

    @property
    def enforced(self) -> bool:
        return self.triggered and self.mode == Mode.ENFORCE and self.blocking

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("modified_text", None)  # may contain user content; never logged
        # Underscore-prefixed details (e.g. the PII placeholder mapping) stay in memory only.
        d["details"] = {k: v for k, v in self.details.items() if not k.startswith("_")}
        return d


@dataclass
class GuardDecision:
    stage: Stage
    action: Action
    text: str                                   # text to forward (possibly redacted / repaired)
    results: list[CheckResult]
    policy_version: str
    latency_ms: float
    blocked_by: list[str] = field(default_factory=list)
    shadow_hits: list[str] = field(default_factory=list)   # would have acted, but in shadow mode

    @property
    def allowed(self) -> bool:
        return self.action != Action.BLOCK

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "action": self.action.value,
            "allowed": self.allowed,
            "policy_version": self.policy_version,
            "latency_ms": round(self.latency_ms, 2),
            "blocked_by": self.blocked_by,
            "shadow_hits": self.shadow_hits,
            "checks": [r.to_dict() for r in self.results],
        }
