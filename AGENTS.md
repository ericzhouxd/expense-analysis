# Project agent instructions

## Start here

- Read `README.md` and the relevant sections of `docs/DEVELOPMENT.md` before editing.
- Keep changes focused on the requested task and explain any assumptions in the final report.
- Work on the current agent branch. Commit completed, verified work locally when asked.
- Do not push branches, open pull requests, deploy, or contact external services unless the user explicitly asks.

## Privacy boundary

- Real financial data is private and must stay local.
- Never read, copy, expose, commit, or use `data/`, `output/`, `config.toml`, `.env*`, or database files as test fixtures.
- Use synthetic data and temporary databases in tests.
- Never place private data under `static/`.

## Runtime and checks

- Use the uv-managed Python 3.12 environment. Run project commands through `uv run`.
- Before finishing a code change, run:

```bash
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

- If a check cannot run, state the exact reason and preserve enough evidence for the user to continue.

## Project conventions

- Keep calculation and validation logic out of Streamlit UI code when possible.
- Store money as positive integer cents and use `transaction_type` for direction.
- Treat refunds separately from expenses and exclude transfers from spending and cash flow.
- Escape every user-supplied value rendered in custom HTML.
- Preserve predictable empty-state behavior and avoid division by zero.
- Follow the architecture, UI, SQLite, and privacy guidance in `docs/DEVELOPMENT.md`.
