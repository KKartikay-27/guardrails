"""Gate a candidate eval report against the committed baseline.

    uv run python evals/compare.py reports/eval.json evals/baseline.json --md reports/pr_comment.md

Exit 1 when the candidate regresses: lower catch rate, higher false-positive rate, lower recall
in any category, or a previously caught case that is now missed. Latency is reported, not gated
(shared CI runners are too noisy for a hard latency gate at sub-millisecond scale).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def outcome_map(report: dict, view: str) -> dict[str, bool]:
    return {c["id"]: c["intervened"] for c in report[view]["cases"]}


def fmt_delta(new: float, old: float, higher_is_better: bool = True) -> str:
    d = new - old
    if abs(d) < 1e-9:
        return "±0"
    good = (d > 0) == higher_is_better
    return f"{'🟢' if good else '🔴'} {d:+.1%}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("baseline")
    ap.add_argument("--view", default="detection", choices=["detection", "as_deployed"])
    ap.add_argument("--tol-catch", type=float, default=0.0, help="allowed absolute drop in catch rate")
    ap.add_argument("--tol-fpr", type=float, default=0.0, help="allowed absolute rise in FPR")
    ap.add_argument("--md", help="write a markdown summary (used as the PR comment)")
    args = ap.parse_args()

    cand, base = json.loads(Path(args.candidate).read_text()), json.loads(Path(args.baseline).read_text())
    cm, bm = cand[args.view]["metrics"], base[args.view]["metrics"]
    failures: list[str] = []

    if cm["catch_rate"] < bm["catch_rate"] - args.tol_catch:
        failures.append(f"catch rate fell {bm['catch_rate']:.1%} → {cm['catch_rate']:.1%}")
    if cm["false_positive_rate"] > bm["false_positive_rate"] + args.tol_fpr:
        failures.append(f"false-positive rate rose {bm['false_positive_rate']:.1%} → {cm['false_positive_rate']:.1%}")
    for cat, b in bm["by_category"].items():
        c = cm["by_category"].get(cat)
        if c and c["recall"] < b["recall"]:
            failures.append(f"`{cat}` recall fell {b['recall']:.0%} → {c['recall']:.0%}")

    co, bo = outcome_map(cand, args.view), outcome_map(base, args.view)
    adv_ids = {c["id"] for c in cand[args.view]["cases"] if c["expect"] != ["allow"]}
    newly_missed = sorted(i for i in adv_ids if bo.get(i) and not co[i])
    newly_caught = sorted(i for i in adv_ids if i in bo and not bo[i] and co[i])
    newly_fp = sorted(i for i in co if i not in adv_ids and co[i] and not bo.get(i, False))
    fixed_fp = sorted(i for i in co if i not in adv_ids and not co[i] and bo.get(i, False))
    if newly_missed:
        failures.append(f"previously caught, now missed: {', '.join(newly_missed)}")

    ok = not failures
    cl, bl = cand[args.view]["latency"]["by_stage_ms"], base[args.view]["latency"]["by_stage_ms"]
    lines = [
        f"## {'✅' if ok else '❌'} Guardrail eval: policy `{cand['policy_version']}` vs baseline `{base['policy_version']}`",
        "",
        f"View: **{args.view}** · {cm['n_adversarial']} adversarial / {cm['n_benign']} benign cases"
        + (f" · judge `{cand['judge']}`" if cand.get("judge") else " · offline (no LLM judge)"),
        "",
        "| metric | baseline | candidate | Δ |",
        "|---|---:|---:|---:|",
        f"| catch rate | {bm['catch_rate']:.1%} | {cm['catch_rate']:.1%} | {fmt_delta(cm['catch_rate'], bm['catch_rate'])} |",
        f"| false-positive rate | {bm['false_positive_rate']:.1%} | {cm['false_positive_rate']:.1%} | "
        f"{fmt_delta(cm['false_positive_rate'], bm['false_positive_rate'], higher_is_better=False)} |",
        f"| exact action | {bm['exact_action_rate']:.1%} | {cm['exact_action_rate']:.1%} | "
        f"{fmt_delta(cm['exact_action_rate'], bm['exact_action_rate'])} |",
    ]
    for stage in sorted(cl):
        if stage in bl:
            lines.append(f"| {stage} guard p99 (ms) | {bl[stage]['p99']:.2f} | {cl[stage]['p99']:.2f} | "
                         f"{cl[stage]['p99'] - bl[stage]['p99']:+.2f} |")
    lines += ["", "<details><summary>Recall by category</summary>", "", "| category | baseline | candidate |",
              "|---|---:|---:|"]
    for cat in sorted(set(bm["by_category"]) | set(cm["by_category"])):
        b, c = bm["by_category"].get(cat, {}), cm["by_category"].get(cat, {})
        lines.append(f"| {cat} | {b.get('recall', 0):.0%} | {c.get('recall', 0):.0%} |")
    lines += ["", "</details>", ""]
    for label, ids in [("Newly missed", newly_missed), ("Newly caught", newly_caught),
                       ("New false positives", newly_fp), ("Fixed false positives", fixed_fp)]:
        if ids:
            lines.append(f"- **{label}:** {', '.join(f'`{i}`' for i in ids)}")
    if failures:
        lines += ["", "### Blocking regressions", *[f"- {f}" for f in failures]]
    md = "\n".join(lines) + "\n"
    print(md)
    if args.md:
        Path(args.md).write_text(md)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
