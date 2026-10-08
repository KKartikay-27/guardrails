.PHONY: install test eval eval-llm baseline baseline-llm regression-demo bench bench-e2e serve load docker

PORT ?= 8848
# Secrets live in .env (gitignored), e.g. ANTHROPIC_API_KEY=..., LANGFUSE_PUBLIC_KEY=...
RUN := uv run $(if $(wildcard .env),--env-file .env,)

install:
	uv sync

test:
	$(RUN) ruff check src evals bench tests && uv run pytest -q

eval:
	$(RUN) python evals/run_eval.py --out reports/eval.json
	$(RUN) python evals/compare.py reports/eval.json evals/baseline.json --md reports/pr_comment.md

# Haiku judge on, both policy profiles. Judge responses are cached in .cache/llm.
eval-llm:
	$(RUN) python evals/run_eval.py --llm --out reports/eval_llm_default.json
	$(RUN) python evals/run_eval.py --llm --policy policies/llm-assisted.yaml --out reports/eval_llm_assisted.json

# Accept the current results as the new bar. Commit the baseline with the policy change.
baseline:
	$(RUN) python evals/run_eval.py --out evals/baseline.json

baseline-llm:
	$(RUN) python evals/run_eval.py --llm --policy policies/llm-assisted.yaml --out evals/baseline_llm.json

# Show the CI gate blocking a plausible-but-bad policy edit.
regression-demo:
	$(RUN) python evals/regression_demo.py

bench:
	$(RUN) python bench/latency.py --iters 20 --out reports/latency.json

# Real upstream + judge, no cache: latency budget and $/request per policy profile (~$0.50).
bench-e2e:
	$(RUN) python bench/e2e.py --n 30 --out reports/e2e.json

serve:
	$(RUN) uvicorn guardrail.server:app --port $(PORT) --reload

load:
	$(RUN) python bench/load.py --host http://localhost:$(PORT)

docker:
	docker build -t guardrail . && docker run --rm -p 7860:7860 $(if $(wildcard .env),--env-file .env,) guardrail
