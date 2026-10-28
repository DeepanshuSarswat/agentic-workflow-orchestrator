.PHONY: setup api ui test eval eval3

setup:
	cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

api:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

ui:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest -q

eval:
	backend/.venv/bin/python evals/run_evals.py

eval3:
	backend/.venv/bin/python evals/run_evals.py --repeats 3
