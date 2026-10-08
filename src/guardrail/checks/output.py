"""Output-only checks: JSON schema validation + repair, grounding, system-prompt leak."""

from __future__ import annotations

import json
import re
from typing import Any

import jsonschema
from json_repair import repair_json

from ..types import Action, CheckContext, CheckResult, Stage
from .base import Check, normalize, register

# --------------------------------------------------------------------------- schema

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json_candidate(text: str) -> str:
    if m := _FENCE.search(text):
        return m.group(1).strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    return text[min(starts):].strip() if starts else text.strip()


def _schema_errors(obj: Any, schema: dict[str, Any]) -> list[str]:
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in v.iter_errors(obj)][:10]


@register
class JSONSchema(Check):
    """Validate the response against the request's JSON schema; repair locally, then via LLM."""

    name = "json_schema"
    stages = frozenset({Stage.OUTPUT})
    default_action = Action.REPAIR
    modifies = True

    async def run(self, text: str, ctx: CheckContext) -> CheckResult:
        schema = ctx.response_schema
        if not schema:
            return self.skip("no response_schema on request")

        try:
            obj = json.loads(text)
            errors = _schema_errors(obj, schema)
            if not errors:
                return self.result(False)
        except json.JSONDecodeError as e:
            errors = [f"invalid JSON: {e.msg}"]

        steps = ["local_repair"]
        repaired = repair_json(_extract_json_candidate(text), return_objects=True)
        remaining = _schema_errors(repaired, schema) if repaired not in ("", None) else ["unparseable"]

        if remaining and self.llm and self.params.get("llm_repair", True):
            steps.append("llm_repair")
            resp = await self.llm.complete(
                [{"role": "user", "content": (
                    "Rewrite this payload so it is valid JSON matching the schema. Keep every value that "
                    f"already fits; do not invent facts.\n\nSchema errors:\n{json.dumps(remaining)}\n\n"
                    f"Payload:\n{text[:8000]}")}],
                max_tokens=2048,
                output_schema=schema,
            )
            try:
                repaired = json.loads(resp.text)
                remaining = _schema_errors(repaired, schema)
            except json.JSONDecodeError:
                pass

        details = {"errors": errors, "repair_steps": steps, "remaining_errors": remaining}
        if remaining:
            # Could not fix it: escalate to block regardless of the configured action.
            r = self.result(True, score=1.0, reason="schema violation (unrepairable)", details=details)
            r.action = Action.BLOCK
            return r
        return self.result(True, score=1.0, reason="schema violation (repaired)",
                           modified_text=json.dumps(repaired), details=details)


# --------------------------------------------------------------------------- grounding

_STOP = set(["a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that", "these", "those", "you", "your", "we", "our", "they", "their", "he", "she", "his", "her", "i", "me", "my", "can", "will", "would", "should", "could", "may", "might", "do", "does", "did", "not", "no", "yes", "so", "than", "too", "very", "just", "also", "about", "into", "over", "under", "up", "down", "out", "more", "most", "less", "some", "any", "all", "each", "such", "which", "who", "whom", "what", "when", "where", "why", "how", "there", "here", "have", "has", "had", "please", "thanks", "thank"])
_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def _content_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", normalize(s)) if w not in _STOP and len(w) > 2}


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".").lstrip("$").rstrip("%") for n in _NUM.findall(s)}


_GROUNDING_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "supported": {"type": "boolean"}},
                "required": ["claim", "supported"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}


_ENUM = re.compile(r"(?m)(^|\s)\d{1,2}[.)](?=\s)")


def lexical_unsupported(answer: str, context: str, min_overlap: float, user_input: str = "") -> list[dict[str, Any]]:
    ctx_words = _content_words(context) | _content_words(user_input)
    ctx_nums = _numbers(context) | _numbers(user_input)
    answer = _ENUM.sub(" ", answer)  # list markers ("1.", "2)") are not factual numbers
    flagged = []
    for sent in filter(None, (s.strip() for s in _SENT.split(answer))):
        words = _content_words(sent)
        if len(words) < 4:
            continue  # greetings, sign-offs
        overlap = len(words & ctx_words) / len(words)
        novel_nums = sorted(_numbers(sent) - ctx_nums)
        if novel_nums or overlap < min_overlap:
            flagged.append({"sentence": sent[:200], "overlap": round(overlap, 2), "novel_numbers": novel_nums})
    return flagged


@register
class Grounding(Check):
    """Hallucination check: is every claim in the answer supported by the supplied context?

    method=lexical  content-word overlap + novel-number detection per sentence (free, ~0.1 ms)
    method=llm      Haiku extracts claims and labels each supported/unsupported
    method=hybrid   lexical first; only sentences it flags are sent to the LLM to confirm
    """

    name = "grounding"
    stages = frozenset({Stage.OUTPUT})

    async def run(self, text: str, ctx: CheckContext) -> CheckResult:
        if not ctx.context_docs:
            return self.skip("no context documents on request")
        context = "\n\n".join(ctx.context_docs)
        method = self.params.get("method", "hybrid")
        min_overlap = float(self.params.get("min_overlap", 0.5))
        max_unsupported = float(self.params.get("max_unsupported_ratio", 0.0))

        flagged = lexical_unsupported(text, context, min_overlap, ctx.user_input or "")
        n_sent = max(1, sum(1 for s in _SENT.split(text) if len(_content_words(s)) >= 4))
        details: dict[str, Any] = {"method": method, "lexical_flags": flagged}

        use_llm = self.llm is not None and (method == "llm" or (method == "hybrid" and flagged))
        if use_llm:
            verdict = await self.llm.judge(
                system="You verify whether an assistant's answer is supported by the reference documents. "
                       "Split the answer into atomic factual claims. A claim is supported only if the documents "
                       "state or directly imply it. Greetings, offers to help, and questions are not claims.",
                prompt=f"<documents>\n{context[:12000]}\n</documents>\n\n<answer>\n{text[:4000]}\n</answer>",
                schema=_GROUNDING_SCHEMA,
                max_tokens=1024,
            )
            claims = verdict["claims"]
            unsupported = [c["claim"] for c in claims if not c["supported"]]
            details["llm_claims"] = claims
            ratio = len(unsupported) / max(1, len(claims))
            reason = f"{len(unsupported)}/{len(claims)} claims unsupported"
        else:
            ratio = len(flagged) / n_sent
            reason = f"{len(flagged)}/{n_sent} sentences weakly grounded"

        triggered = ratio > max_unsupported
        return self.result(triggered, score=round(ratio, 3), reason=reason if triggered else "", details=details)


# --------------------------------------------------------------------------- prompt leak


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


@register
class PromptLeak(Check):
    """Detect system-prompt exfiltration: canary token echo or long verbatim overlap."""

    name = "prompt_leak"
    stages = frozenset({Stage.OUTPUT})

    async def run(self, text: str, ctx: CheckContext) -> CheckResult:
        if ctx.canary and ctx.canary in text:
            return self.result(True, score=1.0, reason="canary token in output", details={"canary": True})
        if not ctx.system_prompt:
            return self.skip("no system prompt")
        n = int(self.params.get("ngram", 8))
        sys_words = normalize(ctx.system_prompt).split()
        out_words = normalize(text).split()
        sys_grams = _ngrams(sys_words, n)
        if not sys_grams:
            return self.result(False)
        overlap = len(_ngrams(out_words, n) & sys_grams) / len(sys_grams)
        threshold = float(self.params.get("threshold", 0.2))
        return self.result(overlap >= threshold, score=round(overlap, 3),
                           reason=f"{overlap:.0%} of system prompt {n}-grams reproduced" if overlap >= threshold else "",
                           details={"ngram_overlap": round(overlap, 3)})
