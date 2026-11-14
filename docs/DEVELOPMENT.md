# 記帳 development guide

## Runtime

The project uses a uv-managed CPython 3.12 runtime:

- `.python-version` pins the Python feature version.
- `uv.toml` requires a uv-managed interpreter and uses a project-local cache.
- `.venv/` contains isolated packages.
- `uv.lock` records the resolved dependency set.

Use `uv run` for every project command. Do not install dependencies into the
global Python or pyenv environment.

## Web interface

The interface is a FastAPI server plus a React single-page app over the Python
modules described under Architecture.

```text
web/ (React 19 + TypeScript + Vite)        src/expense_analysis/server/
  src/lib/      parser, formatting           app.py    routes, security middleware
  src/components/ instrument panel parts     views.py  JSON payload builders (cents)
  src/pages/    one module per page          main.py   `expense-app` entry point
        │  fetch /api/* (JSON, integer cents)        │
        └──────────────────────────────────────────▶ database / analytics / term_budget
```

- `server/views.py` turns database rows into plain JSON payloads. Money is always
  integer cents; dates are ISO strings. It holds no HTTP code, so tests call it
  directly or through `TestClient`.
- `server/app.py` exposes `create_app(database, config_loader, today, dist_dir,
  fonts_dir)`. Every argument is injectable, so tests use a temporary SQLite file,
  default config, and a fixed date.
- `web/src/lib/quickParse.ts` parses one-line quick entries in the browser on every
  keystroke. The server still validates and categorizes on save; `keyword.ts`
  mirrors `categories.keyword_matches` so live suggestions agree with the server.
- The UI never computes budget figures. It renders what `/api/overview`,
  `/api/budget`, and `/api/insights` return.

### Security model

- uvicorn binds to `127.0.0.1` only. A middleware also rejects any `Host` header
  other than `127.0.0.1`, `localhost`, or `[::1]`, which blocks DNS-rebinding pages.
- Every non-GET `/api/*` request must carry `X-Jizhang: 1`. Browsers cannot send a
  custom header cross-site without a CORS preflight, and the server allows no CORS,
  so other websites cannot write to the ledger.
- Responses carry a strict Content-Security-Policy (self only, no inline scripts),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and API
  responses are `Cache-Control: no-store`.
- React escapes every rendered string. Do not use `dangerouslySetInnerHTML`.
- Fonts come from `static/fonts` and `@fontsource/doto`; there are no remote
  requests at runtime.

### Working on the interface

```bash
uv run expense-app --no-browser     # API on 127.0.0.1:8765
npm --prefix web run dev            # Vite on 127.0.0.1:5173, proxies /api to 8765
```

`web/dist/` and `web/node_modules/` are ignored. `expense-app` serves a short
"build the interface first" page when `web/dist/` is missing.

Design rules for the web interface:

- Square corners everywhere (`border-radius: 0`); only LEDs and dots are round.
- The glass panel (`Housing`) tracks the pointer for glare and a slight tilt;
  `prefers-reduced-motion` turns off tilt, rolling digits, the ticker, and flaps.
- Changing numbers roll (`Odometer`), meters fill segment by segment
  (`PaceMeter`), and month labels flip like a departures board (`SplitFlap`).
- Every page needs a deliberate empty state and must work at 390px wide.

## Architecture
```text
web/ (React)  ──/api/*──▶  server/app.py
                              ├── server/views.py
                              ├── database.py, transaction_edits.py
                              ├── import_export.py, categories.py, choices.py
                              ├── analytics.py, spending_summary.py
                              ├── term_budget.py, spending_treatment.py
                              └── models.py, config.py
cli.py ───────────────────────┘ (same modules, no server)
```

- `server/` is the only HTTP layer. Calculation and validation stay in the
  modules below it so the CLI, the server and the tests share one implementation.
- `database.py` owns SQLite schema creation and persistence.
- `transaction_edits.py` saves a batch of edits in one SQLite transaction,
  rejecting stale rows (changed since the client loaded them) and duplicates.
- `models.py` validates dates, amounts, transaction types, IDs, and fingerprints.
- `import_export.py` previews and normalizes CSV data. `decode_csv` accepts
  UTF-8 (with or without BOM), UTF-16, cp1252, and latin-1, since spreadsheet
  exports use all four; anything containing NUL bytes is rejected as
  `CsvDecodeError` rather than parsed as a one-column CSV.
- `categories.py` holds keyword rules and category suggestions; `choices.py`
  shares configured and saved vocabulary (categories, accounts, payment methods)
  and rechecks usage on the server before removing one.
- `analytics.py` converts database rows into Pandas frames and calculates insights.
- `config.py` loads safe defaults and the ignored local `config.toml`.
- `university_presets.py` holds public, dated UCLA reference estimates only.
- `university_presets.py` also holds the UCLA quarter dates (`UCLA_QUARTERS`), copied
  from the Registrar's annual calendar with the date they were checked.
- `term_budget.py` validates budget settings and builds the weekly budget: the
  school periods (quarters, breaks, summer), the weekly line, per-week spent and
  saved, bills and big purchases, all in integer cents.

## Theme and local assets
Fonts are Departure Mono (interface), Doto (LED numerals, from `@fontsource/doto`)
and a two-character Noto Sans TC subset (記帳 wordmark). Departure Mono and the
wordmark live in `static/fonts/` with their OFL licenses; the server mounts that
directory at `/fonts`. **Never place databases, CSVs, configuration, or exports in
`static/`.** Keep private data in the existing ignored directories.

Colors are CSS custom properties at the top of `web/src/styles.css`. The glass,
dot-screen, scanline and bevel effects are CSS only; there are no image assets.

## Data flow
```text
Quick add, row edit or CSV
        ↓
TransactionDraft validation (server)
        ↓
Fingerprint duplicate check
        ↓
SQLite transaction
        ↓
Pandas derived columns, spending summary, term budget
        ↓
JSON in integer cents (server/views.py)
        ↓
React pages
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
additive and does not downgrade a newer schema version. Save validates before
writing and is atomic. No real student profile is included in source control.

Schema version 3 drops the legacy `budgets` table. Its monthly category rows were
superseded by `spending_plans`, so nothing had read or written the table since;
`initialize` removes it from databases created under schema 2. Transactions and
saved settings are untouched by that migration.

The `spending_plans` row now holds `BudgetSettings` (payload `schema_version` 3):
housing type, an optional own weekly amount in cents and the bills (name, amount,
categories, cadence `Monthly` / `Each quarter` / `Once`, due day or date). Older
plan payloads (versions 1 and 2) load through `_from_legacy_plan`: Commitments
bills are kept (Quarterly → Each quarter, Coverage total → Once on the first
coverage month) and the housing benchmark carries over. Targets, buffers,
irregular reserves and payment-month overrides are dropped; nothing is written
until the user saves.

Budget calculation (`term_budget.py`):

- The weekly line is the user's amount, or UCLA's everyday estimate (Food +
  Transportation + Personal for the housing type) divided by `school_weeks()`,
  the Monday-aligned weeks from the start of fall quarter to the end of spring.
- A quarter runs from the Monday of the week the quarter begins to the Sunday
  after it ends. Week 1 starts on the instruction date if it is a Monday,
  otherwise the following Monday; earlier days are Week 0. From the Monday of
  finals the label is Finals week. Gaps between quarters are Winter break,
  Spring break and Summer. Dates outside the stored calendar use calendar months.
- Each Mon–Sun week is compared with the line independently. Finished weeks
  report `saved = line − net everyday spent`, which can be negative. Nothing
  rolls over into the next week.
- A bill counts as `paid` once net Bills spending in its categories reaches
  `PAID_SHARE` (90%) of its amount, and `part` when something smaller was paid.
  A Monthly bill takes the payments nearer its due date than the due dates
  either side (`_paid_window`); other bills take 30 days either side. Unpaid, it
  is `soon` within 7 days of its due date, `late` after it, and `missed` once a
  later due date of the same bill is paid, so an old gap stops asking for
  attention. Bills are sorted with what needs attention first, and
  `bill_totals` counts what is paid and what is still to go.

The published UCLA off-campus totals exceed their displayed component sum by $1.
The reference includes an explicit $1 reconciliation line instead of silently
changing a published component. Tuition is cohort-specific; current campus fees
and insurance are not treated as locked to the tuition cohort.

Schema initialization is idempotent. Connections enable foreign keys and WAL
journaling.

## UI conventions
- Dark instrument panel: near-black housing, amber/lime LED readouts, square corners.
- The `HeroNumber` in the glass `Housing` is what has been spent: this week and
  this month side by side on the Overview, this week on Budgets. What is left is
  a readout beneath it. A figure compared with an earlier stretch is worded by
  `versus` in `web/src/lib/format.ts` ("▲ $12.00 (8.0%) more than Oct 1–14")
  wherever it appears.
- Cards carry no captions describing themselves. A card hint is for a figure
  (a total, a count), and how-to text belongs in an empty state.
- Banners (`_signals` in `server/views.py`) are only for things that can be
  acted on, and each carries the `action` that fixes it.
- Color roles: lime for primary actions and healthy pace, amber for caution, coral
  for overage or errors, sage for positive status. Category colors come from
  `web/src/lib/glyphs.ts`.
- Advanced detail goes behind `Collapsible` sections.
- Render user text as React children only; never build HTML strings.

## Adding analytics

Add pure calculation functions to `analytics.py` and test them with synthetic
frames. UI code should format results but should not duplicate business logic.

Month-over-month and year-over-year windows use `models.comparable_day`: a partial
month compares the same days (clamped to a shorter month), and a complete month
compares with the other month in full. Format money for display with
`models.format_dollars` (U+2212 minus; `signed=True` for deltas).

`spending_forecast` projects the month in progress and the months after it from
an exponentially weighted average of the complete months (`FORECAST_SMOOTHING`).
Given `kind_of` (a day → `quarter`/`break`/`summer` lookup such as
`term_budget.period_kind_lookup()`), it also learns how each kind of day
compares with an average day, shrunk toward 1 for kinds seen on few days
(`FORECAST_SHRINK_DAYS`), and scales each month by the mix of days it holds;
`weekly_rates` reports what a week of each kind costs. Its range is the mean
absolute error of replaying that forecast one month ahead over the recorded
months, using only what was known before each. The trend and the forecast
always look from today, whichever month a page has open;
`monthly_spending(through=today)` and `weekly_spending(through=today)` keep a
month or week with nothing spent yet on the chart.

Column charts (`DotColumns`, `WeekBars`) share `usePreview` in
`web/src/components/charts.tsx`: hover or focus describes a column in the
readout bar, a click or Enter picks it, a first tap previews and a second picks,
and arrow keys move between columns. `DotColumns` draws at one unit per pixel and
shows only as many columns as fit, so its labels never overlap. It takes generic
`Column`s; `monthColumns` and `weekColumns` build them, which is how weeks and
months are drawn the same way.

Category keyword rules use `models.keyword_matches` (ASCII word edges plus plural
endings; other scripts match as substrings). `web/src/lib/keyword.ts` mirrors it
as `keywordMatches`, so change both together.

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
npm --prefix web test
npm --prefix web run build
```

Tests must use synthetic data and temporary databases. They must never read or
copy the real database. `tests/test_server.py` drives the API through
`TestClient` with a temporary SQLite file, default config and a fixed date,
covering the security headers, quick add, edits, import, budgets and settings.
`test_term_budget.py` covers the UCLA calendar (Week 0, finals week, breaks,
fallback months), the weekly line, fresh weeks and saved amounts, bills and big
purchases, past terms, validation and legacy payload conversion.

## Student product roadmap

See [Student product roadmap](STUDENT_ROADMAP.md) for the boundary between this
single-user local release and a future UCLA/multi-university product. Do not host
the current global cached database as a shared multi-user service.

## Privacy checklist before committing

1. Confirm `data/`, `output/`, `.venv/`, `.uv-cache/`, and root `config.toml` are
   ignored.
2. Review `git status --ignored`.
3. Search commit candidates for account names, secrets, or transaction details.
4. Run the complete verification suite.

## Spending treatments

`spending_treatment.py` supplies shared classification for budgets, historical
analytics, and the CLI. Category defaults and transaction exceptions are stored
under `spending_rules` in the existing local `category_settings` JSON; category
renames migrate those defaults atomically. Exceptions take priority over category
defaults, which take priority over plan category mappings. Unreviewed categories
consume everyday allowance conservatively and carry an explicit review flag.

Bill categories default to Commitments (shown as **Bills**); `Irregular` is shown
as **Big stuff**. Only Everyday spending is compared with the weekly line. Legacy
`reserve` keys in saved rules are ignored. Transfers and income never count.

Removing a category, account or payment method goes through `delete_choice`,
which rechecks references on the server. Unused choices are removed immediately
with an Undo (`restore_choice`); used ones need a replacement, and the client
only receives a short preview of the affected transactions.
