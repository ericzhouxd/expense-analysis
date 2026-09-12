# 記帳

A private, local-first expense tracker and analysis dashboard. Transactions stay in
an ignored SQLite database on your computer; the app binds only to `127.0.0.1` and
Streamlit telemetry is disabled.

## Documentation

- [User guide](docs/USER_GUIDE.md): day-to-day workflows, imports, budgets, and insights
- [Development guide](docs/DEVELOPMENT.md): architecture, data model, UI conventions, and verification

## Start the app

This project uses a uv-managed Python 3.12 runtime and a project-local `.venv`.
It does not use packages from pyenv or the global Python installation.

```bash
uv sync --all-groups
uv run streamlit run app.py
```

Open <http://127.0.0.1:8501>. You do not need to activate the environment because
`uv run` selects it automatically.

## Import CSV data

Upload a CSV from the Import / Export page to preview and validate it before
anything is saved. You can also import a local file from the command line:

```bash
uv run expense-import /path/to/transactions.csv
```

Import validation handles quoted commas, currency formatting, refunds, missing
fields, unknown categories, category rules, and duplicate transactions.

## What the app includes

- Quick transaction entry from the Transactions page with keyboard progression
- Searchable, filterable, bulk-editable transaction table
- Explicit expenses, refunds, income, and transfers
- CSV preview, validation, duplicate detection, import, and export
- KPI cards and interactive category and monthly charts
- 3-, 6-, and 12-month rolling calculations
- Like-for-like month and year comparisons
- Partial-period labels and end-of-month run-rate projections
- UCLA monthly/quarterly spending plans with cohort tuition, bill reserves and everyday allowance
- Spending-driver, recurring-charge, and anomaly analysis
- Cash-flow, savings-rate, and academic-period analysis
- Sharp editorial/Y2K interface with brushed-metal and halftone textures
- Light and dark themes with locally bundled Departure Mono interface typography

## Local commands

Switch appearance with **System / Light / Dark** at the bottom of the sidebar.

```bash
# Add a transaction interactively
uv run expense-add

# Print the latest summary
uv run expense-analyze

# Export a private local backup (output/ is ignored)
uv run expense-export
```

## Configuration

Copy the example and customize the local copy:

```bash
cp config.example.toml config.toml
```

`config.toml` is ignored by Git. It supports:

- Personal and fixed categories
- Account and payment-method choices
- Entry defaults
- Keyword-based category rules
- Academic-period month defaults
- Exact academic-period start and end dates

## Privacy model

The following are excluded from Git:

- `data/`, including the SQLite database and original CSV
- `output/`, including charts and exported backups
- Root `config.toml`
- `.env` files
- `.venv`, uv caches, and Python tooling caches

Only application code, tests, documentation, and example configuration belong in
the GitHub repository. Real transactions and generated exports remain local.

## Development checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

The same commands run in CI on every push and pull request
(`.github/workflows/checks.yml`).

To have them applied automatically before each commit:

```bash
uv run pre-commit install
```

The hooks in `.pre-commit-config.yaml` run the same pinned ruff and mypy from
`uv.lock` and additionally refuse to commit `data/`, `output/`, `config.toml`,
and database or `.env` files.

All tests use synthetic data and temporary databases.

## License

Released under the [MIT License](LICENSE).

The bundled fonts in `static/fonts/` are third-party works under the SIL Open Font
License and are not covered by the MIT License above. See
[static/fonts/README.md](static/fonts/README.md) for the per-font license files.
