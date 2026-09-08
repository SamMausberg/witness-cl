.PHONY: test experiment audit-power paper formal clean

test:
	PYTHONPATH=src python -m pytest -q --junitxml=artifacts/pytest.xml
experiment:
	PYTHONPATH=src python experiments/synthetic.py --seeds 20 --episodes 384 --out artifacts/synthetic
audit-power:
	PYTHONPATH=src python experiments/audit_power.py
paper:
	python tools/paper_tables.py
	python tools/render_bibliography.py
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
	cd paper && pdflatex -interaction=nonstopmode -halt-on-error main.tex
formal:
	cd formal && lake build
clean:
	cd paper && latexmk -c
