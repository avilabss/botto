format:
    uv run ruff format .
    uv run ruff check --fix .

lint:
    uv run ruff check .

typecheck:
    uv run mypy

test:
    uv run pytest

check: 
    lint typecheck test
