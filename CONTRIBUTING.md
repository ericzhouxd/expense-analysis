# Contributing

## Before you start

- Keep real transactions, exports, and `config.toml` out of the repository. Tests
  use synthetic data and temporary databases only.
- Read [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the architecture and the
  conventions.

## Checks

```bash
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
npm --prefix web test
npm --prefix web run build   # strict type check, then the production build
```

`uv run pre-commit install` runs the Python checks before each commit.

## Pull requests

- One issue per pull request.
- Add a test that fails without the change. API behavior belongs in
  `tests/test_server.py`; browser-side parsing in `web/src/lib/*.test.ts`.
- Say what you verified, and how.
