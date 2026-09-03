.PHONY: install ingest index test eval app demo clean fmt

PY ?= python

install:
	uv venv || python -m venv .venv
	. .venv/bin/activate && pip install -U pip && pip install -e ".[dev,evals,guardrails]"

ingest:
	. .venv/bin/activate && $(PY) scripts/ingest.py

index:
	. .venv/bin/activate && $(PY) scripts/build_policy_index.py

test:
	. .venv/bin/activate && pytest

eval:
	. .venv/bin/activate && $(PY) evals/run_langsmith.py

app:
	. .venv/bin/activate && streamlit run app/streamlit_app.py

demo: ingest index
	. .venv/bin/activate && streamlit run app/streamlit_app.py

fmt:
	. .venv/bin/activate && ruff check --fix . && ruff format .

clean:
	rm -rf data/aura.db data/checkpoints.db data/chroma __pycache__ .pytest_cache .ruff_cache
