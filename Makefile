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

CAMPAIGN_PYTHON = \
	experiments/delayed_sql.py \
	src/witness_cl/delayed_memory.py \
	src/witness_cl/campaign_env.py \
	src/witness_cl/campaign_analysis.py \
	src/witness_cl/campaign_io.py \
	src/witness_cl/model_campaign.py \
	src/witness_cl/ace_memory.py \
	src/witness_cl/query_memory.py \
	src/witness_cl/source_views.py \
	src/witness_cl/relational_program.py \
	integrations/clbench/ace.py \
	integrations/clbench/witness.py \
	tools/campaign.py \
	tools/campaign_runtime.py \
	tools/campaign_results.py \
	tools/campaign_sequence.py \
	tools/campaign_auxiliary_sequence.py \
	tools/campaign_supervisor.py \
	tools/campaign_pilot_report.py \
	tools/campaign_assay.py \
	tools/native_campaign.py \
	tools/publish_campaign.py \
	tools/audit_campaign_mechanism.py

.PHONY: test lint format formal paper technical-report legacy-audit v9-audit cpp-check cuda-check clean

test:
	mkdir -p $(TEST_ARTIFACTS)
	PYTHONPATH=src $(PYTHON) -m pytest -q --junitxml=$(TEST_ARTIFACTS)/pytest.xml
lint:
	$(RUFF) check $(CURRENT_PYTHON)
	$(RUFF) format --check $(CURRENT_PYTHON)
	$(RUFF) check $(CAMPAIGN_PYTHON)
format:
	$(RUFF) format $(CURRENT_PYTHON)
formal:
	$(PYTHON) formal/audit_v10.py --output artifacts/v10
paper:
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && bibtex main
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex

technical-report:
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error technical_report.tex
	cd paper && bibtex technical_report
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error technical_report.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error technical_report.tex
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
