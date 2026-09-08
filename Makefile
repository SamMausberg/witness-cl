.PHONY: test experiment audit-power refine refine-learning refine-audit refine-training cube-bench cpp-check cuda-check paper formal clean

test:
	mkdir -p artifacts/v3
	PYTHONPATH=src python -m pytest -q --junitxml=artifacts/v3/pytest.xml
experiment:
	PYTHONPATH=src python experiments/synthetic.py --seeds 20 --episodes 384 --out artifacts/synthetic
audit-power:
	PYTHONPATH=src python experiments/audit_power.py
refine: refine-learning refine-audit refine-training cube-bench
refine-learning:
	PYTHONPATH=src python experiments/refinement.py --part arithmetic --seeds 20
	PYTHONPATH=src python experiments/refinement.py --part relational --seeds 20
	PYTHONPATH=src python experiments/integrated.py --seeds 20
refine-audit:
	PYTHONPATH=src python experiments/refinement.py --part audit
refine-training:
	PYTHONPATH=src python experiments/refinement.py --part training --seeds 20
	PYTHONPATH=src python experiments/refinement.py --part tracking --seeds 20
cube-bench:
	PYTHONPATH=src python experiments/cube_bench.py
cpp-check:
	$(MAKE) -C kernels cpu-check
	bash tools/check_v3_cpp.sh
cuda-check:
	$(MAKE) -C kernels cuda-check
paper:
	python tools/v3_tables.py
	python tools/render_bibliography.py
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
formal:
	cd formal && lake build
clean:
	rm -f paper/*.aux paper/*.log paper/*.out paper/*.bbl paper/*.blg
	$(MAKE) -C kernels clean

.PHONY: continuation-study neural-study continuation-diagnostics
continuation-study:
	PYTHONPATH=src python experiments/continuation.py --seeds 20 --episodes 64 --out artifacts/v3
neural-study:
	PYTHONPATH=src python experiments/versioned_training.py --seeds 20 --episodes 1600 --out artifacts/v3
continuation-diagnostics:
	PYTHONPATH=src python experiments/continuation_diagnostics.py --trials 1000 --out artifacts/v3
