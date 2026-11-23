# 記帳

A private, local-first expense tracker and analysis dashboard. Transactions stay in
an ignored SQLite database on your computer, and the app answers only on
`127.0.0.1`.

## Documentation

- [User guide](docs/USER_GUIDE.md): day-to-day workflows, imports, budgets, and insights
- [Development guide](docs/DEVELOPMENT.md): architecture, data model, UI conventions, and verification

## Start the app

This project uses a uv-managed Python 3.12 runtime and a project-local `.venv`.
It does not use packages from pyenv or the global Python installation. The
interface is a small React app that needs Node.js 20.19 or newer to build once.

```bash
uv sync --all-groups
npm --prefix web ci
npm --prefix web run build
uv run expense-app
```

`expense-app` serves the built interface and its local API on
<http://127.0.0.1:8765> and opens it in your browser (`--no-browser` skips that,
`--port` changes the port). Rebuild the interface after pulling changes to `web/`.

## Import CSV data

Choose or drop a CSV under **Settings → Import & export** to preview and validate it
before anything is saved. You can also import a local file from the command line:

```bash
uv run expense-import /path/to/transactions.csv
```

Import validation handles quoted commas, currency formatting, refunds, bank-style
negative amounts, missing fields, unknown categories, category rules, and duplicate
transactions. A backup exported by the app re-imports cleanly as duplicates.

## What the app includes

- An overview that leads with this week against the weekly line and this month against
  the last, followed by what needs attention, where the money went and what is due
- ⌘K quick add: type `12.50 chipotle lunch yesterday apple pay` and press Enter, log a
  repeat purchase again in two keys, search transactions, or jump to a page
- Day-grouped transaction list with inline editing, keyboard navigation, bulk
  category/treatment changes, and Undo for deletes
- Explicit expenses, refunds, income, and transfers
- CSV preview, validation, duplicate detection, category mapping, import, and export
- Categories suggested from your own earlier entries, learning from corrections, with the
  evidence one press away
- 3-, 6-, and 12-month rolling averages and like-for-like comparisons
- Weekly budget line on the real UCLA quarter calendar (Week 0, Weeks 1–10, finals),
  with unspent money counted as saved; bills and big purchases stay outside it
- A budget with nothing to set up: where you live, which cost of attendance is yours,
  your bills and how each purchase counts are worked out from your own records, with the
  reason shown and a way to overrule each one
- Cost-of-attendance check: whether the whole school year, tuition and rent included,
  will pass UCLA's COA, with a likely range learned from your own weeks, the weekly
  spending that stays under it, and how the same method did on your earlier years
- Spending drivers, and the largest recent purchases
- Cash-flow, savings-rate, and academic-period analysis
- Square-cornered dark "instrument" design with LED panels, a purchase ticker and a dot
  calendar, in locally bundled Departure Mono and Doto type. Its lists, date pickers and
  menus are its own, it works on a phone and from the keyboard, and it makes no network
  requests

## Local commands

```bash
# Add a transaction interactively
uv run expense-add

# Print the latest summary
uv run expense-analyze

# Import a CSV whose purchases are negative numbers (bank style)
uv run expense-import --negative-expenses refund /path/to/transactions.csv

# Export a private, dated local backup (output/ is ignored)
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

The web interface has its own checks:

```bash
npm --prefix web test        # parser and formatting unit tests
npm --prefix web run build   # strict type check, then the production build
```

All of these run in CI on every push and pull request
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
