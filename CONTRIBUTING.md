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
uv run pytest -m rendered   # needs Chromium; excluded from the default run
```

`uv run pre-commit install` runs the same checks before each commit.
`uv run pytest -m rendered` boots the app in a real browser and measures the DOM;
use it for anything the browser decides, such as box sizes and focus rings.

## Pull requests

- One issue per pull request.
- Add a test that fails without the change. Prefer a rendered check over a
  substring match against the stylesheet when the question is what the user sees.
- Say what you verified, and how.
