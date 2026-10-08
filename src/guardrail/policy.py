from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .types import Action, Mode, Stage


class CheckPolicy(BaseModel):
    id: str
    check: str                                  # registered check type, e.g. "pii"
    mode: Mode | None = None                    # falls back to policy defaults
    blocking: bool | None = None                # False = run async, log only, add no latency
    action: Action | None = None                # override the check's default action
    timeout_ms: int | None = None
    on_error: Literal["allow", "block"] | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class Defaults(BaseModel):
    mode: Mode = Mode.SHADOW
    blocking: bool = True
    timeout_ms: int = 2000
    on_error: Literal["allow", "block"] = "allow"   # fail open by default; flip per check


class Policy(BaseModel):
    version: str
    product: str = "default"
    description: str = ""
    defaults: Defaults = Field(default_factory=Defaults)
    block_message: str = "Sorry, I can't help with that request."
    input: list[CheckPolicy] = Field(default_factory=list)
    context: list[CheckPolicy] = Field(default_factory=list)
    output: list[CheckPolicy] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill_defaults_and_validate(self) -> Policy:
        seen: set[str] = set()
        for stage in Stage:
            for cp in self.stage(stage):
                if cp.id in seen:
                    raise ValueError(f"duplicate policy id: {cp.id}")
                seen.add(cp.id)
                cp.mode = cp.mode or self.defaults.mode
                cp.blocking = self.defaults.blocking if cp.blocking is None else cp.blocking
                cp.timeout_ms = cp.timeout_ms or self.defaults.timeout_ms
                cp.on_error = cp.on_error or self.defaults.on_error
        return self

    def stage(self, stage: Stage) -> list[CheckPolicy]:
        return {Stage.INPUT: self.input, Stage.CONTEXT: self.context, Stage.OUTPUT: self.output}[stage]

    def all_checks(self) -> list[tuple[Stage, CheckPolicy]]:
        return [(s, cp) for s in Stage for cp in self.stage(s)]

    def with_mode(self, mode: Mode, only: set[str] | None = None) -> Policy:
        """Copy with every (or the selected) check forced to one mode. Used by evals."""
        p = self.model_copy(deep=True)
        for _, cp in p.all_checks():
            if only is None or cp.id in only:
                cp.mode = mode
        return p

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:12]


def load_policy(path: str | Path) -> Policy:
    with open(path) as f:
        return Policy.model_validate(yaml.safe_load(f))
