.PHONY: setup demo dev test check build
setup:
	python3 -m venv .venv
	.venv/bin/pip install -r backend/requirements-dev.txt
	npm --prefix user_panel ci
	npm --prefix admin_panel ci
demo:
	.venv/bin/python scripts/demo.py
dev:
	.venv/bin/python scripts/dev.py
test:
	.venv/bin/pytest -q
check:
	.venv/bin/ruff check backend scripts
	npm --prefix user_panel run lint
	npm --prefix admin_panel run lint
build:
	npm --prefix user_panel run build
	npm --prefix admin_panel run build
