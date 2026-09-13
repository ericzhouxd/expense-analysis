# 記帳 development guide

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
- `transaction_edits.py` validates table edits and saves reviewed batches in one
  SQLite transaction, checking duplicates and changes since the editor snapshot.
- `models.py` validates dates, amounts, transaction types, IDs, and fingerprints.
- `import_export.py` previews and normalizes CSV data.
- `analytics.py` converts database rows into Pandas frames and calculates insights.
- `config.py` loads safe defaults and the ignored local `config.toml`.
- `university_presets.py` holds public, dated UCLA reference estimates only.
- `spending_plan.py` validates private plans and calculates bill reserves and rollover
  in integer cents, independent of Streamlit and UCLA-specific tables.
- `budget_ui.py` handles plan setup, monthly/quarterly views and payment allocations.
- `presentation.py` renders escaped, data-independent visual components and loads
  the shared theme from `assets/theme.css`.

## Theme and local assets

Streamlit 1.60+ is required for paired native theme configuration and the trusted
static theme bridge. `.streamlit/config.toml` defines native Light/Dark colors,
square controls, a 14px base size, and locally hosted font faces. Users choose System,
Light, or Dark from the sidebar Appearance control; the built-in top-right menu stays
hidden.

`assets/theme_bridge.html` observes the native app background and updates a single
theme attribute for custom CSS panels. The sidebar Appearance control selects the same
native System/Light/Dark themes as Streamlit's built-in switcher, so it does not create
a second theme state. The bridge also makes Plotly charts keyboard-focusable and
toggles their local fullscreen class. It runs only bundled static JavaScript: never
interpolate transaction content, read storage, or issue network requests. It disconnects
its previous observers and listeners on reruns. Plotly uses transparent surfaces and
inherits the native theme's text colors.

`assets/choice_bridge.html` confirms creation in native React Aria single selects,
Base Web multiselects, and Glide table choice editors. It reads the active input
locally and renders prompt text with `textContent`; it never sends or stores input.
Window capture listeners run before form Enter navigation, and are cleaned up on
reruns. Check Enter, Escape, mouse selection, partial matches, and both themes after
Streamlit upgrades. `choices.py` shares configured and saved vocabulary. Editable
table fields use creatable multiselect columns; transaction validation enforces one
value per field, while budget bills may map multiple categories. Calculation enums
(transaction type, billing cycle, and reference presets) keep fixed choices.

The three families are Departure Mono (UI), Anton (condensed amounts), and a
two-character Noto Sans TC subset (記帳 wordmark). Fonts and their OFL licenses live
in `static/fonts/`. Static serving is enabled only for public visual assets:
**never place databases, CSVs, configuration, or exports in `static/`.** Keep
private data in the existing ignored directories. CSS generates the brushed metal
and halftone; the small chrome ornament is inline SVG, not an external image.

Check theme switching without a Python rerun, mobile stacking, large/negative
amounts, and the data editor whenever changing presentation. Custom HTML must use
`st.html`, with all dynamic text escaped, to avoid Markdown code-block regressions.

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

Schema version 2 adds `spending_plans` with one active local row (`id = 1`), a
validated versioned JSON payload and an update timestamp. Initialization is
additive and does not downgrade a newer schema version. The payload contains the
reference snapshot, custom target, bill coverage/category rules, buffer and
transaction-ID-to-budget-month overrides. Save validates before writing and is
atomic. No real student profile is included in source control.

Schema version 3 drops the legacy `budgets` table. Its monthly category rows were
superseded by `spending_plans`, so nothing had read or written the table since;
`initialize` removes it from databases created under schema 2. Transactions and
saved plans are untouched by that migration.

Reserve accounting uses `max(planned, expense − refunds)` per bill cycle. This
amount is allocated across its coverage with integer remainder distribution.
Actual paid plus remaining reserve equals the effective committed cost. Every
expense/refund is matched at most once; overlapping category/coverage rules are
rejected, and all unmatched expenses count as flexible. Targets are allocated to
the first nine months, with separate summer funding for the last three. The buffer
is spread over the whole plan. Flexible allowance is smoothed within each quarter.
Monthly remaining is cumulative within a quarter, not additive across months.

The published UCLA off-campus totals exceed their displayed component sum by $1.
The reference includes an explicit $1 reconciliation line instead of silently
changing a published component. Tuition is cohort-specific; current campus fees
and insurance are not treated as locked to the tuition cohort.

Schema initialization is idempotent. Connections enable foreign keys and WAL
journaling.

## UI conventions

The interface balances a sharp editorial grid with early-web character:

- Off-white or near-black canvas with acid-lime accents
- Square panels, compact typography, brushed-metal bars, and dotted balances
- Three locally hosted font families; no decorative slogans or campus photography
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
uv run mypy
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
    "Import / Export",
    "Budgets",
    "Advanced insights",
    "Settings",
]:
    app.sidebar.radio[0].set_value(page).run(timeout=30)
    assert not app.exception, (page, app.exception)
'
```

Tests must use synthetic data and temporary databases. They must never read or
copy the real database.
The automated all-pages regression in `test_spending_plan.py` injects a temporary
database and default config. Prefer that test over the manual audit above, which
opens the locally configured database. The suite covers setup confirmation,
persistence, cohort totals, reserves, refunds, overages, payment-date overrides,
summer, cent rounding, invalid coverage and quarter rollover.

## Student product roadmap

See [Student product roadmap](STUDENT_ROADMAP.md) for the boundary between this
single-user local release and a future UCLA/multi-university product. Do not host
the current global cached database as a shared multi-user service.

## Privacy checklist before committing

1. Confirm `data/`, `output/`, `.venv/`, `.uv-cache/`, and root `config.toml` are
   ignored.
2. Review `git status --ignored`.
3. Confirm `.streamlit/config.toml` is tracked; it enforces localhost and disables
   telemetry.
4. Search commit candidates for account names, secrets, or transaction details.
5. Run the complete verification suite.
