# Speaker notes and 15-minute rehearsal plan

13 slides, 15:00 total, followed by 5:00 Q&A. Suggested speaking assignments follow the supplied team order and can be adjusted. They do not assert implementation ownership.

| Slide | Topic | Time | Suggested speaker |
|---|---|---|---|
| 1 | Guardrails & Safety Layer for an LLM Product | 0:00–0:25 | Tammana Mohan |
| 2 | Problem statement | 0:25–1:55 | Tammana Mohan |
| 3 | Objectives & requirements | 1:55–3:00 | Kumar Kartikay |
| 4 | System overview | 3:00–4:00 | Kumar Kartikay |
| 5 | Architecture | 4:00–6:05 | Mayank Gupta |
| 6 | Guardrails & safety mechanisms | 6:05–7:10 | Suryansh Dubey |
| 7 | Core workflow / request lifecycle | 7:10–8:15 | Suryansh Dubey |
| 8 | Implementation & operations | 8:15–9:20 | Abhishek Shah |
| 9 | Testing & evaluation | 9:20–10:40 | Abhishek Shah |
| 10 | Example scenarios / demonstration | 10:40–11:55 | Daksh Kanaujia |
| 11 | Limitations & future scope | 11:55–13:05 | Daksh Kanaujia |
| 12 | Conclusion | 13:05–14:20 | Utkersh Basnet |
| 13 | Team Members | 14:20–15:00 | Utkersh Basnet |

## 1. Guardrails & Safety Layer for an LLM Product

Introduce the system as a guardrails service surrounding an LLM support assistant. Our focus is observable, versioned intervention before and after generation. The demo domain is a small SaaS help centre. The presentation covers what the code implements and separates recorded experiments from fresh local verification.

Sources: README.md; src/guardrail/pipeline.py; product/system_prompt.md

## 2. Problem statement

Frame the problem as protecting a support workflow rather than guaranteeing that an LLM is safe. Inputs include the most recent user question, retrieved or supplied documents, and a candidate model response. The guard target is an expected stage action. The model’s output is the support answer. Explain why retrieved documents are an instruction-injection surface and why an output contract needs independent validation. The business aim is to reduce unsafe output and sensitive-data exposure without blocking legitimate customers. Our evaluation measures intervention and false positives, not business savings or a production security guarantee.

Sources: src/guardrail/types.py; src/guardrail/pipeline.py; evals/run_eval.py

## 3. Objectives & requirements

Functional requirements map directly to policy checks, the three guard surfaces, and the evaluation gate. The numerical pilot targets are proposed from the existing evidence, not requirements supplied by the instructor or measured service-level guarantees. The fresh offline suite meets its detection and false-positive targets. Recorded real-model benchmarks meet the pattern-profile latency targets, while the judged blocking profile does not. A fresh single-worker mixed-endpoint mock load test reached 263.8 requests per second rather than the prior recorded 436.5, so the proposed scale target is not met by this run. Explain that runtime and workload conditions matter.

Sources: policies/default.yaml; deliverables/evaluation/results/offline_eval.json; reports/e2e.json; deliverables/evaluation/results/load_local.json

## 4. System overview

Walk left to right. The service accepts JSON messages at POST /v1/chat. The input guard handles the last user message. If it allows the request, BM25 retrieves up to two help-centre documents unless the caller supplies context. The context guard checks documents and drops poisoned ones. The upstream receives the remaining context and a per-request canary in the system prompt. The output guard then validates and may redact, repair or block the generated answer. A context block is local to the document; it does not automatically refuse the user’s request. The response exposes decisions and timings for inspection.

Sources: src/guardrail/server.py; src/guardrail/pipeline.py

## 5. Architecture

The HTTP layer validates request shape with Pydantic. GuardedAssistant owns the request lifecycle and joins decisions by a request ID. Guard loads a versioned policy and executes the configured checks. Independent blocking detectors run concurrently, while modifying checks run in sequence so each sees the previous transformed text. The upstream is either a hosted Anthropic client or a deterministic mock, not a model hosted inside the container. BM25 operates over local Markdown documents; there is no vector database. Decision logs write through a background thread, and Langfuse export runs asynchronously. Prometheus scrapes the metrics endpoint. Optional non-blocking checks execute in background tasks and do not gate the response. Explain the API integration alternative: POST /v1/guard/{stage} checks one stage for an external application. Model-serving, control policy and telemetry are distinct responsibilities.

Sources: src/guardrail/server.py; src/guardrail/engine.py; src/guardrail/pipeline.py; src/guardrail/telemetry.py; src/guardrail/tracing.py

## 6. Guardrails & safety mechanisms

Describe patterns as the default offline detectors. Optional model assistance adds semantic judgments for inputs, documents and grounding; optional heavyweight classifier dependencies exist but were not demonstrated in this package. PII and input secrets are redacted. Output secret detection blocks. JSON validation can perform local or LLM repair. Prompt leakage uses a per-request canary plus overlap with the system prompt. Grounding compares the answer with provided documents and can use an LLM judge. Toxicity on angry customer input remains shadow by default. Detection capability is different from enforced production behavior, which is why both evaluation views matter.

Sources: policies/default.yaml; policies/llm-assisted.yaml; src/guardrail/checks/

## 7. Core workflow / request lifecycle

Point to the distinction between stage decisions and individual detector findings. A modifying action keeps the request moving using changed text. A blocking input decision stops before generation. A blocked retrieved document is excluded, while other context survives. The output stage may validate or repair JSON and redact sensitive text before releasing it. If output is blocked, the service returns the configured policy message. The engine folds severity as block, redact, repair, allow. Off checks skip execution; shadow checks execute without enforcing. Non-blocking checks start as background tasks and never change the decision, even if they finish before the response. Shadow mode controls enforcement, while blocking controls whether execution is awaited. A shadow check can therefore still add latency. There is no implemented human-escalation workflow to claim here.

Sources: src/guardrail/engine.py; src/guardrail/pipeline.py; src/guardrail/types.py

## 8. Implementation & operations

Explain choices rather than reading a tool list. FastAPI and Pydantic keep request validation and inspection straightforward. YAML makes safety changes reviewable in Git. Five short local documents justify BM25 without adding an embedding pipeline or vector service. Prometheus/Grafana expose operational latency and errors, input trigger rates, and output intervention rates, covering at least three monitoring categories. Offline quality has the regression suite; online grounding can run as a shadow judge, but no production user study or automated drift detector is claimed. Deploy the Docker image with a selected policy, observe new checks in shadow, then promote after manual review. Roll back by restoring the prior image or policy and restarting; policy loading occurs at startup. Upstream cost is available, but judge-inclusive per-request cost attribution remains incomplete. The runbook has precise setup and proposed alert thresholds.

Sources: pyproject.toml; Dockerfile; ops/docker-compose.yml; src/guardrail/tracing.py; deliverables/observability/README.md

## 9. Testing & evaluation

The repository describes 68 adversarial and 61 benign cases as hand-written and labelled. These include 35 hard negatives and 12 attack categories. The evaluator runs the same engine used by the service. Catch rate counts block, redact or repair, so it is not automatically successful prevention of the intended attack. Exact-action rate is separately reported. Explain the two views: forced enforcement measures detector capability, configured modes measure current interventions. The 98.5 percent judged result is a prior repository report and was not rerun for this submission. A fresh offline run reproduced the pattern scores. The regression demonstration makes an apparently attractive threshold change, reduces false positives and loses attacks; the gate rejects it. Limitations include a small, tuned set, incomplete multi-turn cases and shared upstream/judge model bias.

Sources: deliverables/evaluation/results/offline_eval.json; reports/eval_llm_assisted.json; deliverables/verification/tests.txt; deliverables/evaluation/results/regression_gate.md

## 10. Example scenarios / demonstration

Use up to 60 seconds for the prepared local demonstration and 15 seconds to explain telemetry. Show the three saved or live requests in order. First a legitimate support question passes, then the direct injection is blocked, then the synthetic email is redacted while the request continues. Inspect the response decision and timings. Be clear that the mock response demonstrates orchestration and policy behavior rather than real-model answer quality. If the local service is unavailable, open deliverables/observability/evidence/requests_mock.json and identify it as saved evidence. The Grafana screenshot is a prior repository artifact. Do not present that screenshot as a current live session.

Sources: deliverables/observability/evidence/requests_mock.json; deliverables/observability/evidence/metrics_mock.prom

## 11. Limitations & future scope

Use specific limitations instead of vague statements about future accuracy. The residual paraphrased prompt leak is pl-003. The current pipeline forwards earlier messages without the latest-message input screening. Our known cases are useful for preventing regressions but do not prove unseen attack robustness. Judge and answering model can make correlated mistakes. Request-level upstream accounting excludes judge costs, and output-blocked responses omit usage. Public launch also needs authentication, rate limiting and access-controlled observability. These are future improvements, not features we added. At ten times traffic, test upstream rate limits and worker queueing first, then redesign the local spend ledger for concurrency.

Sources: src/guardrail/pipeline.py; src/guardrail/llm.py; reports/eval_llm_assisted.json; deliverables/observability/README.md

## 12. Conclusion

State three explicit choices. We chose patterns over judging every request by default because the recorded pattern guard p99 was 7.8 milliseconds versus about 7.04 seconds with blocking judges, at about $0.000955 versus $0.004038 per request including the upstream. We chose shadow over immediate enforcement for grounding and input toxicity because legitimate requests can trigger those checks. We chose BM25 over a vector database because five short documents do not justify the extra dependency without measured retrieval benefit. The model judge raises all-enforced catch from 85.3 to 98.5 percent on this set, so selective enforcement is a real trade-off rather than a universally better option. The deck reports recorded benchmark costs rather than current vendor prices. These are sample p99s from 30 requests per profile, not production tail guarantees. Finish by emphasizing an auditable policy and a release decision supported by evaluation. Invite direct questions and acknowledge uncertainty when evidence is missing.

Sources: reports/e2e.json; policies/default.yaml; src/guardrail/pipeline.py; README.md

## 13. Team Members

Introduce the team in the displayed order, then transition to the five-minute Q&A. The speaking plan in the companion notes is a proposed allocation for rehearsal, not a claim about each member’s implementation contribution. All names and emails match the supplied brief, including the capital S in Suryansh’s email.

Sources: User-supplied presentation brief
