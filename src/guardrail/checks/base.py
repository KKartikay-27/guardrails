from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from ..llm import LLMClient
from ..types import Action, CheckContext, CheckResult, Stage

REGISTRY: dict[str, type[Check]] = {}


def register(cls: type[Check]) -> type[Check]:
    REGISTRY[cls.name] = cls
    return cls


class Check(ABC):
    name: ClassVar[str]
    stages: ClassVar[frozenset[Stage]]
    default_action: ClassVar[Action] = Action.BLOCK
    modifies: ClassVar[bool] = False   # returns modified_text (redact / repair); run sequentially

    def __init__(self, policy_id: str, params: dict[str, Any], action: Action | None, llm: LLMClient | None):
        self.policy_id = policy_id
        self.params = params
        self.action = action or self.default_action
        self.llm = llm

    def result(self, triggered: bool, **kw: Any) -> CheckResult:
        return CheckResult(policy_id=self.policy_id, check=self.name, triggered=triggered, action=self.action, **kw)

    def skip(self, reason: str) -> CheckResult:
        return CheckResult(policy_id=self.policy_id, check=self.name, triggered=False, skipped=True, reason=reason)

    @abstractmethod
    async def run(self, text: str, ctx: CheckContext) -> CheckResult: ...


# Zero-width and bidi control characters used to smuggle tokens past naive filters.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


def normalize(text: str, leet: bool = False) -> str:
    """NFKC-fold homoglyphs/fullwidth chars, drop invisible chars, collapse whitespace."""
    t = unicodedata.normalize("NFKC", text)
    t = _INVISIBLE.sub("", t)
    t = re.sub(r"\s+", " ", t).lower()
    if leet:
        t = t.translate(_LEET)
    return t
