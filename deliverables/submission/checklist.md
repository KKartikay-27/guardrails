# Submission checklist and rubric audit

Reviewed against both supplied PDFs on 8 October 2026. Status describes available evidence, not an instructor-assigned score.

| Checklist item | Status | Evidence / remaining action |
|---|---|---|
| Live deployment | Optional, not supplied | README explicitly states this; local startup instructions present |
| GitHub repository | Public access verified | `https://github.com/KKartikay-27/guardrails`; GitHub API confirms public access and a description; final package still needs a commit/push |
| README problem and architecture | Present | Root README and presentation slides 2-5 |
| README numbers | Present | Catch/FPR, latency, costs, throughput; fresh and recorded evidence separated |
| README setup and live link | Setup present; live URL unavailable | Root README; optional deployment status explicit |
| Versioned prompts/config | Present | `product/system_prompt.md`, `policies/*.yaml`, `product/kb/*.md` |
| Domain-specific handwritten eval | Existing set packaged | 68 adversarial + 61 benign cases; team to confirm original human authorship |
| Eval scoring documented | Present | `evaluation/README.md`, case-level JSON, baseline comparison |
| Cost and latency per request | Partial coverage, limits documented | API timings/upstream usage, optional traces; judge attribution and output-blocked usage gap remain |
| Dashboard/traces | Dashboard/config and sample evidence present | Grafana JSON + recorded screenshot + fresh local metrics; hosted Langfuse not verified |
| 15-minute presentation + 5-minute Q&A | Materials prepared | Deck, timed notes, demo and Q&A guide; team rehearsal pending |
| Equitable team participation | Proposed allocation prepared | Names/emails supplied; `team.md` and timed speaker blocks, rehearsal pending |
| Resume line | Present | `resume.md`, three-sentence version |
| Peer review readiness | Blank worksheet present | Personally complete assigned reviews during the event and submit within 10 minutes |
| Repository commit/submission | Pending | Changes are local; final review, commit and push remain |

## Presentation rubric

| Criterion | Weight | Evidence in presentation | Honest limitation / preparation |
|---|---:|---|---|
| Problem framing | 20% | Slides 2-3: objective, input/output/target, numerical pilot targets, scope | Targets are proposed and not production guarantees |
| Architecture | 30% | Slides 4-5 and 7: components, labelled interactions, JSON APIs, ordering and async behavior | Small local KB, hosted upstream, last-message input coverage |
| LLMOps depth | 20% | Slides 8-9 and accompanying speaker notes: offline gate, monitoring categories, online shadow judging, deployment and rollback | No real user study, automated drift alerting or verified hosted traces |
| Trade-offs | 20% | Slides 11-12 and accompanying speaker notes: measured cost/quality/latency, >=3 justified choices, failures and scale | Paid-model results are historical repository evidence |
| Presentation quality | 10% | 15-minute timing plan, demonstration, direct Q&A prompts | Names/emails added; speaking assignments and actual rehearsal need confirmation |

## Final manual check before submitting

- [x] Add supplied team names/emails.
- [ ] Confirm suggested speaking assignments.
- [ ] Confirm repository is public and the final package is committed and pushed.
- [ ] Confirm the reviewer can open the PowerPoint deck in the intended presentation app.
- [ ] Rehearse all speaking blocks with the demo inside 15 minutes.
- [ ] Keep the mock demonstration and recorded evidence available if network/API access fails.
- [ ] If supplying a live URL, verify it matches the final repository version.
- [ ] Open the official peer-review sheets and confirm assigned teams.

No claim of full rubric compliance or a guaranteed grade is made. The main technical gap is complete judge-inclusive per-request cost attribution; the main administrative gaps are rehearsal and final repository publication.
