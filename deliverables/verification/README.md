# Verification record

Date: 8 October 2026 (Asia/Kolkata). Base repository commit: `af88807b912a792ac953c16bccf4cbea65ef06d0`. Package and README edits are local and uncommitted.

| Check | Outcome | Evidence |
|---|---|---|
| Dependency install | Passed, `uv sync --frozen` | Repository lockfile unchanged |
| Ruff | Passed | `lint.txt` |
| Existing test suite | 29 passed | `tests.txt` |
| Offline evaluation | 85.3% catch / 4.9% FPR; configured modes 75.0% / 3.3% | `evaluation.txt`, `../evaluation/results/offline_eval.json` |
| Baseline gate | Passed, no regression | `baseline_gate.txt` |
| Deliberately weakened threshold | Gate rejected with expected exit 1 | `regression.txt` |
| Pattern latency | 20 iterations over 129 cases | `latency.txt`, `../evaluation/results/latency_local.json` |
| Local HTTP probes | Support allowed, injection blocked, synthetic PII redacted | `../observability/evidence/requests_mock.json` |
| Mock load | 263.8 req/s, 0 HTTP errors, 50 clients, 20.2 s | `load.txt` |
| GitHub public access | API HTTP 200, private=false, main branch and description present | `repository.json` |

Load p50/p99: 124.56 / 1002.67 ms. This fresh run does not meet the proposed 400 req/s pilot target. The unseeded mixed-endpoint load benchmark measures HTTP status/transport errors, not answer correctness. Other local preparation work ran during this session. Treat differences from the prior run as observations requiring a controlled comparison, not a diagnosed regression.

Fresh latency microbenchmark blocking p50/p99 (ms):

- context: 0.53 / 0.77
- input: 0.358 / 0.569
- output: 0.355 / 0.664

The microbenchmark replays stages sequentially; evaluator case latencies include bounded concurrent execution. Those measurements are different from HTTP end-to-end latency.

No paid-model calls, external deployment, Git push or hosted Langfuse verification was performed. Grafana dashboard JSON parses successfully, but the provided screenshot is historical and the Docker stack was not started during this verification.

Presentation checks and local link/data integrity checks are recorded after final artifact creation in `package_checks.txt`.

## GitGuardian fixture remediation

The user confirmed both flagged values were invented test data. The two affected cases now use named markers and deliberately nonfunctional runtime fixtures. A matching literal in the existing HTTP test was also removed. Broad GitGuardian exclusions were removed so these files remain in scan scope. Four regression tests cover fixture detection and marker storage; the current suite has 33 tests. See `fixture_remediation_tests.txt`, `fixture_remediation_lint.txt`, `fixture_remediation_scan.txt`, and `fixture_remediation_gate.txt`. Existing verification and presentation test counts describe the earlier 29-test run. This update does not claim that the remote GitGuardian check passed or that previous commits were purged.
