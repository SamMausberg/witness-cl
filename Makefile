PYTHON ?= python3
RUFF ?= .venv/bin/ruff
TEST_ARTIFACTS ?= artifacts/v10
CURRENT_PYTHON = \
	experiments/stateful_sql.py \
	src/witness_cl/evidence_memory.py \
	formal/audit_v10.py \
	tools/replay_study.py \
	tools/replay_at_revision.py \
	tools/current_results.py \
	tools/gh200_runtime.py \
	tools/replay_legacy.py \
	tests/test_stateful_sql.py \
	tests/test_gh200_runtime.py \
	tests/test_replay_study.py \
	tests/test_legacy_replay.py \
	tests/test_replay_at_revision.py \
	tests/test_current_results.py \
	tests/test_formal_v10.py

.PHONY: test lint format formal paper legacy-audit v9-audit cpp-check cuda-check clean

test:
	mkdir -p $(TEST_ARTIFACTS)
	PYTHONPATH=src $(PYTHON) -m pytest -q --junitxml=$(TEST_ARTIFACTS)/pytest.xml
lint:
	$(RUFF) check $(CURRENT_PYTHON)
	$(RUFF) format --check $(CURRENT_PYTHON)
format:
	$(RUFF) format $(CURRENT_PYTHON)
formal:
	$(PYTHON) formal/audit_v10.py --output artifacts/v10
paper:
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && bibtex main
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
legacy-audit:
	$(PYTHON) tools/replay_legacy.py --output artifacts/v10/legacy-replay.json
v9-audit: legacy-audit
cpp-check:
	$(MAKE) -C kernels cpu-check
	bash tools/check_v3_cpp.sh
	PYTHONPATH=src $(PYTHON) tools/check_v4_cpp.py
cuda-check:
	$(MAKE) -C kernels cuda-check
clean:
	rm -f paper/*.aux paper/*.log paper/*.out paper/*.bbl paper/*.blg
	$(MAKE) -C kernels clean
