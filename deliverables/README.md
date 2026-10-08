# Guardrail submission package

A policy-driven safety layer for a SaaS support assistant. Start with the presentation, then use the evaluation and observability evidence to reproduce its claims.

| Deliverable | Entry point |
|---|---|
| Presentation | [15-minute deck](presentation/guardrail_capstone.pptx), [speaker notes](presentation/speaker_notes.md), [demo and Q&A](presentation/demo_and_qa.md) |
| Evaluation set | [Scoring and dataset card](evaluation/README.md), [68 adversarial cases](evaluation/redteam.jsonl), [61 benign cases](evaluation/benign.jsonl) |
| Observability | [Runbook and monitoring plan](observability/README.md), [dashboard](observability/guardrail-dashboard.json), [request evidence](observability/evidence/requests_mock.json) |
| Submission audit | [Checklist and rubric mapping](submission/checklist.md) |
| Team | [Details to complete](submission/team.md) |
| Resume | [Resume-ready description](submission/resume.md) |
| Peer review | [Blank worksheet and rules](submission/peer_review.md) |
| Verification | [Verification record](verification/README.md) |

Repository: https://github.com/KKartikay-27/guardrails

Prepared on 8 October 2026. The user-supplied checklist and rubric are preserved in `submission/`. No public live deployment URL was supplied. Local startup is documented in the repository README. Deployment is optional under the supplied checklist.

## Evidence provenance

`evaluation/results/offline_eval.json`, `latency_local.json`, and `load_local.json` are fresh local measurements. `recorded_*.json` files are unchanged copies of existing repository reports, including paid-model experiments. Those model experiments were not rerun for this package. The dashboard screenshot is also an existing repository artifact. Mock request samples are fresh and have zero model cost by construction.

The copied datasets and dashboard are submission snapshots. Edit their canonical versions in `evals/data/` and `ops/grafana/`, then refresh these copies. `submission/manifest.json` records SHA-256 hashes for reproducibility.

## Remaining submission actions

Team names and emails are included in the requested order; confirm the proposed speaking assignments. Rehearse the deck to 15 minutes plus 5 minutes Q&A. Confirm the final commit on GitHub, then commit/push this package through your normal workflow. Complete assigned peer reviews personally during the actual presentations. These actions are not marked complete in the audit.
