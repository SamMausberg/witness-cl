PYTHON ?= python3
.PHONY: test experiment audit-power refine refine-learning refine-audit refine-training cube-bench cpp-check cuda-check paper formal clean

test:
	mkdir -p artifacts/v5
	PYTHONPATH=src $(PYTHON) -m pytest -q --junitxml=artifacts/v5/pytest.xml
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
	$(PYTHON) tools/v4_tables.py
	$(PYTHON) tools/v5_tables.py
	$(PYTHON) tools/render_bibliography.py
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
formal:
	$(PYTHON) formal/audit.py --output artifacts/v5
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
