# Local Spending development guide

## Runtime

The project uses a uv-managed CPython 3.12 runtime:

- `.python-version` pins the Python feature version.
- `uv.toml` requires a uv-managed interpreter and uses a project-local cache.
- `.venv/` contains isolated packages.
- `uv.lock` records the resolved dependency set.

Use `uv run` for every project command. Do not install dependencies into the
global Python or pyenv environment.

## Architecture

```text
app.py
  └── expense_analysis.ui
        ├── expense_analysis.database
        ├── expense_analysis.import_export
        ├── expense_analysis.analytics
        ├── expense_analysis.models
        └── expense_analysis.config
```

- `app.py` is the Streamlit entry point.
- `ui.py` renders pages and translates UI actions into database operations.
- `database.py` owns SQLite schema creation and persistence.
- `models.py` validates dates, amounts, transaction types, IDs, and fingerprints.
- `import_export.py` previews and normalizes CSV data.
- `analytics.py` converts database rows into Pandas frames and calculates insights.
- `config.py` loads safe defaults and the ignored local `config.toml`.

The analytics and storage layers do not depend on Streamlit.

## Data flow

```text
Manual entry or CSV
        ↓
TransactionDraft validation
        ↓
Fingerprint duplicate check
        ↓
SQLite transaction
        ↓
Pandas derived columns
        ↓
Metrics and Plotly figures
        ↓
Streamlit pages
```

Money is stored as positive integer cents. `transaction_type` determines the
direction used in spending and cash-flow calculations.

## SQLite schema

`transactions` contains:

- Stable UUID-like text ID
- ISO transaction date
- Description, merchant, category, account, and payment method
- Positive integer `amount_cents`
- Explicit transaction type
- Notes and duplicate fingerprint
- Creation and update timestamps

`budgets` uses `(month, category)` as its primary key and stores integer cents.

Schema initialization is idempotent. Connections enable foreign keys and WAL
journaling.

## UI conventions

The interface follows a lightweight “calm finance” system:

- Warm neutral canvas
- Restrained green, gold, and coral accents
- One primary visual message per section
- Advanced comparisons hidden behind progressive disclosure
- List view for reading and data editor for bulk changes

Custom visual fragments must be rendered with `st.html()`. Do not pass indented
HTML through `st.markdown()`: Markdown may display it as a code block. Use
`st.markdown()` only for genuine Markdown content.

Any user-supplied value included in HTML must go through `_safe_inline()` or
`html.escape()`. Never interpolate raw transaction data into markup.

## Adding analytics

Add pure calculation functions to `analytics.py` and test them with synthetic
frames. UI code should format results but should not duplicate business logic.

Analytics must:

- Return predictable empty frames when no data is available
- Treat refunds separately from expenses
- Exclude transfers from spending and cash flow
- Label or normalize partial periods
- Avoid division by zero
- Avoid silently classifying unknown categories as personal spending

## Verification

Run:

```bash
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

The rendered-page audit uses Streamlit’s `AppTest`:

```bash
uv run python -c '
from streamlit.testing.v1 import AppTest
app = AppTest.from_file("app.py").run(timeout=30)
for page in [
    "Overview",
    "Transactions",
    "Add transaction",
    "Import / Export",
    "Budgets",
    "Advanced insights",
    "Settings",
]:
    app.radio[0].set_value(page).run(timeout=30)
    assert not app.exception, (page, app.exception)
'
```

Tests must use synthetic data and temporary databases. They must never read or
copy the real database.

## Privacy checklist before committing

1. Confirm `data/`, `output/`, `.venv/`, `.uv-cache/`, and root `config.toml` are
   ignored.
2. Review `git status --ignored`.
3. Confirm `.streamlit/config.toml` is tracked; it enforces localhost and disables
   telemetry.
4. Search commit candidates for account names, secrets, or transaction details.
5. Run the complete verification suite.
