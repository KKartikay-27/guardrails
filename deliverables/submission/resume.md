# Resume-ready description

Built a versioned guardrails service for a SaaS support assistant with input, retrieved-context and output checks, a 129-case evaluation suite, and a CI gate that rejects safety regressions. Reproduced 85.3% adversarial catch rate with 4.9% false positives in offline all-enforced evaluation; recorded LLM-assisted experiments reached 98.5% catch rate at approximately $0.004 per request and 7.04 seconds p99 guard overhead. Added Prometheus/Grafana monitoring, optional Langfuse tracing, and shadow-to-enforce policy controls.

Use the description only for work you can explain and attribute accurately. The LLM-assisted catch rate and cost/latency come from separate recorded experiments; the catch metric counts any intervention, and the configured deployed catch rate is lower because some checks run in shadow.
