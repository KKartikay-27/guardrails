## ✅ Guardrail eval: policy `2026.10.0` vs baseline `2026.10.0`

View: **detection** · 68 adversarial / 61 benign cases · offline (no LLM judge)

| metric | baseline | candidate | Δ |
|---|---:|---:|---:|
| catch rate | 85.3% | 85.3% | ±0 |
| false-positive rate | 4.9% | 4.9% | ±0 |
| exact action | 85.3% | 85.3% | ±0 |
| context guard p99 (ms) | 1.43 | 1.44 | +0.01 |
| input guard p99 (ms) | 1.73 | 1.62 | -0.10 |
| output guard p99 (ms) | 1.44 | 1.45 | +0.01 |

<details><summary>Recall by category</summary>

| category | baseline | candidate |
|---|---:|---:|
| hallucination | 83% | 83% |
| indirect_injection | 75% | 75% |
| jailbreak | 67% | 67% |
| pii | 100% | 100% |
| pii_leak | 100% | 100% |
| prompt_injection | 73% | 73% |
| prompt_leak | 67% | 67% |
| schema | 100% | 100% |
| secret_leak | 100% | 100% |
| secrets | 100% | 100% |
| topic | 100% | 100% |
| toxicity | 100% | 100% |

</details>

