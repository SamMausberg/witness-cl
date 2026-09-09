PYTHON ?= python3
.PHONY: test experiment audit-power refine refine-learning refine-audit refine-training cube-bench cpp-check cuda-check paper formal clean

test:
	mkdir -p artifacts/v8
	PYTHONPATH=src $(PYTHON) -m pytest -q --junitxml=artifacts/v8/pytest.xml
experiment:
	PYTHONPATH=src $(PYTHON) experiments/synthetic.py --seeds 20 --episodes 384 --out artifacts/synthetic
audit-power:
	PYTHONPATH=src $(PYTHON) experiments/audit_power.py
refine: refine-learning refine-audit refine-training cube-bench
refine-learning:
	PYTHONPATH=src $(PYTHON) experiments/refinement.py --part arithmetic --seeds 20
	PYTHONPATH=src $(PYTHON) experiments/refinement.py --part relational --seeds 20
	PYTHONPATH=src $(PYTHON) experiments/integrated.py --seeds 20
refine-audit:
	PYTHONPATH=src $(PYTHON) experiments/refinement.py --part audit
refine-training:
	PYTHONPATH=src $(PYTHON) experiments/refinement.py --part training --seeds 20
	PYTHONPATH=src $(PYTHON) experiments/refinement.py --part tracking --seeds 20
cube-bench:
	PYTHONPATH=src $(PYTHON) experiments/cube_bench.py
cpp-check:
	$(MAKE) -C kernels cpu-check
	bash tools/check_v3_cpp.sh
	PYTHONPATH=src $(PYTHON) tools/check_v4_cpp.py
cuda-check:
	$(MAKE) -C kernels cuda-check
paper:
	$(PYTHON) tools/v8_results.py
	$(PYTHON) tools/render_bibliography.py
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
formal:
	$(PYTHON) formal/audit_v8.py --output artifacts/v8
clean:
	rm -f paper/*.aux paper/*.log paper/*.out paper/*.bbl paper/*.blg
	$(MAKE) -C kernels clean

.PHONY: continuation-study neural-study continuation-diagnostics
continuation-study:
	PYTHONPATH=src $(PYTHON) experiments/continuation.py --seeds 20 --episodes 64 --out artifacts/v3
neural-study:
	PYTHONPATH=src $(PYTHON) experiments/versioned_training.py --seeds 20 --episodes 1600 --out artifacts/v3
continuation-diagnostics:
	PYTHONPATH=src $(PYTHON) experiments/continuation_diagnostics.py --trials 1000 --out artifacts/v3

.PHONY: latent-study latent-heldout latent-diagnostics holdout-audit
latent-study:
	PYTHONPATH=src $(PYTHON) experiments/latent_continuation.py --seeds 20 --episodes 48 --out artifacts/v4
latent-heldout:
	PYTHONPATH=src $(PYTHON) experiments/latent_continuation.py --seeds 100 --seed-offset 10000 --episodes 48 --out artifacts/v4/heldout
latent-diagnostics:
	PYTHONPATH=src $(PYTHON) experiments/latent_diagnostics.py --out artifacts/v4
holdout-audit:
	PYTHONPATH=src $(PYTHON) tools/audit_v4_holdout.py

.PHONY: relational-development relational-heldout relational-audit
V7_OUT ?= artifacts/v7/new-development
relational-development:
	OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src $(PYTHON) experiments/relational_v7.py --seeds 80000 80001 80002 80003 --protocol both --out $(V7_OUT)
relational-heldout:
	OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONPATH=src $(PYTHON) experiments/relational_v7.py --seeds 81000 81001 81002 81003 81004 81005 81006 81007 81008 81009 81010 81011 81012 81013 81014 81015 --protocol both --freeze artifacts/v7/freeze.json --out $(V7_OUT)
relational-audit:
	PYTHONPATH=src $(PYTHON) experiments/audit_relational_v7.py artifacts/v7/holdout --freeze artifacts/v7/freeze.json --out artifacts/v7/holdout-replay.json

.PHONY: sql-abstraction-audit
sql-abstraction-audit:
	PYTHONPATH=src $(PYTHON) experiments/audit_sql_abstractions_v8.py artifacts/v8/development --freeze artifacts/v8/prepilot-freeze.json --output artifacts/v8/development-replay.json
