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
  src/components/ shared primitives          views.py  JSON payload builders (cents)
  src/pages/    one module per page          main.py   `expense-app` entry point
  src/styles.css  tokens, then parts
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
  keystroke. The server validates and categorizes; `keyword.ts` mirrors
  `models.keyword_matches` to find a known merchant in the line.
- `/api/bootstrap` sends `frequent`, the purchases most likely to be logged again
  (`analytics.frequent_entries`); `web/src/lib/palette.ts` matches what is typed
  against them.
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
- `instrument.tsx` holds the LED parts (`Housing`, `HeroNumber`, `Odometer`, `PaceMeter`,
  `SplitFlap`, `Ticker`, `Readout`, `Delta`, `Lamps`, `Pips`, `Band`, `Led`, `Glyph`) and `charts.tsx` the dot-matrix
  charts. `Housing` is the glass panel.
  Use one per page, for the figure the page leads with; the rest are `Card`s.
- Page parts come from `ui.tsx` (`PageHead`, `Card`, `Tabs`, `Segmented`, `Stepper`,
  `Fold`, `Menu`, `Info`, `Notice`, `Empty`, `Loading`, `LoadError`) and `feedback.tsx`
  (`Modal`, toasts). Add to them rather than styling a one-off on a page.
- Never use a native `<select>`, date input, datalist or number input: the browser draws
  those in its own style. Use `Select`, `MultiSelect` and `DatePicker` from
  `pickers.tsx`, `ChoiceCombo` for a list that can grow, and `Menu` for actions. All of
  them open in `Popover`, which uses the browser's top layer so nothing clips them.
- Chart columns are a whole number of 6-unit dots, so no dot is cut.
- Every page is a `PageHead`, with its `Tabs` in it if it has parts, then panels and cards.
  Each tab is its own path (`BUDGET_TABS`, `SETTINGS_TABS` in `router.ts`), so it can be
  linked to.
- Small view choices (scope, trend unit, average window) go through `usePref` in
  `lib/prefs.ts`. They live in this browser only and losing them must not matter.
  Filters live in the URL.
- Every page needs a deliberate empty state and must work at 390px wide and from the
  keyboard. The page tabs move to the bottom of the screen below 720px.
- `prefers-reduced-motion` turns off the ticker and every animation.

## Architecture
```text
web/ (React)  ──/api/*──▶  server/app.py
                              ├── server/views.py
                              ├── database.py, transaction_edits.py
                              ├── import_export.py, choices.py
                              ├── categories.py ─▶ category_learning.py
                              ├── analytics.py, spending_summary.py
                              ├── replay.py ─▶ autopilot.py, coa_outlook.py
                              ├── patterns.py, forecast.py
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
- `category_learning.py` learns categories from earlier entries (`CategoryHistory`),
  and `categories.suggest_category` ranks that against rules, built-in words and the
  default category. It is the only implementation: quick add asks `/api/suggest` while
  typing and the server decides again on save. Replay a ledger before changing its
  constants.
- `categories.py` holds keyword rules and category suggestions; `choices.py`
  shares configured and saved vocabulary (categories, accounts, payment methods)
  and rechecks usage on the server before removing one.
- `analytics.py` converts database rows into Pandas frames and calculates insights.
- `config.py` loads safe defaults and the ignored local `config.toml`. Entry defaults
  chosen in Settings are `entry_defaults` in `category_settings`; `effective_config`
  puts them over the configured ones, and renames carry them along.
- `university_presets.py` holds public, dated UCLA reference estimates only.
- `university_presets.py` also holds the UCLA quarter dates (`UCLA_QUARTERS`), copied
  from the Registrar's annual calendar with the date they were checked.
- `term_budget.py` validates budget settings and builds the weekly budget: the
  school periods (quarters, breaks, summer), the weekly line, per-week spent and
  saved, bills and the totals outside it, all in integer cents.
- `patterns.py` finds repeating charges, school charges, rent and lumpy categories
  in the ledger; `forecast.py` learns a spending level from a student's own weeks.
- `autopilot.py` turns what those find, plus the student's choices, into the
  settings and rules everything else uses; `coa_outlook.py` projects the school year.
- `replay.py` is what `server/` and `cli.py` call. `smart_budget` adds each Monday's
  line and the track record on earlier years.

## Theme and local assets
Fonts are Departure Mono (interface), Doto (LED numerals, from `@fontsource/doto`)
and a two-character Noto Sans TC subset (記帳 wordmark, traditional characters only).
Departure Mono and the wordmark live in `static/fonts/` with their OFL licenses; the
server mounts that directory at `/fonts`. **Never place databases, CSVs, configuration,
or exports in `static/`.** Keep private data in the existing ignored directories.

The interface is dark only. Colors, the sunken-box and raised-key surfaces, control
heights, card padding and gaps are CSS custom properties at the top of
`web/src/styles.css`; LED colors used in SVG are `LED` in `lib/glyphs.ts`. The glass,
dot-screen, scanline and bevel effects are CSS only. There are no image assets: icons
(`icons.tsx`) and category glyphs (`glyphs.ts`) are drawn from pixel grids.

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

`category_corrections` holds the IDs of entries whose category was set by hand (changed
later, or picked against a suggestion) and when. Deleting an entry keeps its row, so
Undo restores the correction too.

The `spending_plans` row now holds `BudgetSettings` (payload `schema_version` 3):
housing type, an optional own weekly amount in cents and the bills (name, amount,
categories, cadence `Monthly` / `Each quarter` / `Once`, due day or date, and
optionally `match` words and `pinned`). `pinned` on the settings names the answers
the student chose and `dismissed` the learned bills set aside; both are optional
keys, so older payloads load without them and mean "nothing chosen". Older
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
  attention. Bills are sorted with what needs attention first. Only `late` ones
  are shown, as an Overview tile; the rest feed the school-year outlook.

Automatic budget (`patterns.py`, `autopilot.py`):

- Saved settings are never rewritten by learning. `resolve(saved, rules, rows,
  as_of)` returns effective `BudgetSettings`, rules and the `Fact`s behind them.
  Order of trust: pinned by the student, shown by the ledger, saved before the
  budget was automatic, then a default. Each fact carries its source, the reason,
  and the automatic answer even when it is overruled.
- Learned state lives in memory only. Nothing learned is written to SQLite, a
  file or a log, and no amounts, merchants or dates from a real ledger are in
  source, tests or docs. Constants are general (a jump must be this unlikely);
  everything specific to a student comes from their rows at run time.
- `_kind` caches and `replay._cache` are keyed by content, so an edited row is
  learned from at once. `replay._cache` is bounded and lives with the process.
- `quarter_charges` groups school charges by the quarter they pay for.
  `infer_profile` compares them with UCLA's published charges for each cohort,
  residency and UC SHIP combination; `AGAINST_EVIDENCE_CENTS` penalizes
  combinations that other evidence (an own plan, the first recorded year)
  contradicts, so a nearer amount alone cannot outvote it.
- `rent_payments` runs before `quarter_charges`, so rent as large as a room
  charge is never read as campus housing.
- `repeating_charges` finds monthly and yearly series by name and spacing. A
  series that stopped is `moved_on`: it leaves the forecast instead of lingering.
- A saved bill is replaced by a learned one it describes (`_replaces`) unless it
  is pinned.
- `legacy_suggestion` is the old category suggestion. Until the student saves
  from the new page (`rules["auto"]`), a saved treatment equal to it is not
  treated as a choice, so old one-click defaults do not block learning.

Cost of attendance (`coa_outlook.py`, `forecast.py`, `replay.py`):

- Without a profile, or outside the preset's year, the outlook returns
  `ready: False` and a reason instead of a guess.
- `projected` is the exact sum of five integer-cent layers: recorded, due,
  everyday, one_offs, assumed. The per-part table sums to the same number.
- `counts` decides which school year a purchase pays for: a written school year
  first, then the bill it was matched to, then `EARLY_PARTS` and `EARLY_TRIP`
  before Week 0. `arrival` finds move-in.
- `school_year_dues` gives a monthly bill nine or ten due dates, depending on
  whether its June date falls before finals end. Payments belong to the due date
  whose window holds them, so a monthly payment claimed by none is left out.
- `everyday_rate` splits history where the level clearly jumps (`stretch_start`)
  and learns from the current stretch. `memory` replays the recorded weeks inside
  stretches to choose a half-life and to scale the range by how wrong it was.
  `DRIFT` and `FRESH_YEAR` add what past weeks cannot show: the level wanders,
  and a school year that has just begun may differ from the last. Breaks use the
  ratio to class weeks of their own stretch, shrunk by `KIND_SHRINK_WEEKS`.
- `one_off_rate` blends the past year's pace with the same stretch of earlier
  years. Bill categories, school charges, and deposits named for a year are never
  in a pace, because their schedules cover them.
- Missing school charges and housing are raised to the published figure, less
  what a bundled payment above the published school charges covers.
- `replay` runs the same functions on the ledger as it stood on an earlier day.
  It gives each Monday its own line (`LINE_FLOOR` of UCLA's estimate at least)
  and says what the projection would have been at this point of finished years.
  `Habits.spread` widens the range when those missed by more than their own range
  allowed; `SPREAD_WEIGHT` keeps one year from deciding it alone.
- `spending_rules.parts` holds category → COA part corrections; `coa_part` guesses
  the rest from keywords. Renames and removals migrate both maps.

`PUT /api/budget/settings` takes the page's whole state: `housing`, `cohort`,
`residency`, `insurance`, `weekly_cents`, `total_cents`, `bills`, `dismissed`.
`null` means automatic. `settle` keeps what was saved before as the fallback and
records the rest as pinned.

The published UCLA off-campus totals exceed their displayed component sum by $1.
The reference includes an explicit $1 reconciliation line instead of silently
changing a published component. Tuition is cohort-specific; current campus fees
and insurance are not treated as locked to the tuition cohort.

Schema initialization is idempotent. Connections enable foreign keys and WAL
journaling.

## UI conventions
- The first figure on a page is what has been spent (`Spent`): this week and this
  month side by side on the Overview, this week on Budget. What is left is a line
  beneath it. A figure compared with an earlier stretch is a `Delta` ("▲ $12.00 8% OCT 1–14"),
  whose accessible name is the full sentence from `versus` in `web/src/lib/format.ts`.
- No captions: no sentences that explain a figure, a chart or a control. A card hint is
  for a figure (a total, a count). Show state with a part from `instrument.tsx` instead:
  `Delta` (change), `Lamps` (which of a few), `Pips` (a count out of a few), `Band` (a
  range), `PaceMeter`'s `cap` and `today` (a limit, the day). Each part takes the
  sentence as its accessible name.
- A reason that must stay reachable goes in an `Info` popover, opened by a `?` key or by
  the row's own lamp.
- `_signals` in `server/views.py` are only for things that can be acted on. Each has a
  `label` and `value` for its Overview tile, a `text` sentence for screen readers and
  the `action` that fixes it.
- Color roles: lime for lit, current and the primary action; coral for over or failed,
  sage for saved or received, amber for the line, forecasts and what needs attention, blue
  for what is set by hand or expected. A colored figure always says the same thing in
  words. Categories have their own color and glyph (`categoryColor`, `Glyph`).
- Advanced detail goes behind a `Fold`; occasional actions go in a row's `Menu`.
- Anything that can be undone happens at once and offers **Undo** in its toast.
  Confirm only what cannot be undone or needs a decision.
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

`ColumnChart`, `DayBars`, `WeekChart` and `CashFlowChart` share `usePreview` in
`web/src/components/charts.tsx`: hover or focus describes a column in the `Readout`,
a click or Enter picks it, a first tap previews and a second picks, and arrow keys
move between columns. `ColumnChart` draws at one unit per pixel and shows only as many
columns as fit, so its labels never overlap. It takes generic `Column`s;
`monthColumns` and `weekColumns` build them, which is how weeks and months are drawn
the same way. Columns are at most 24px wide with a rounded data end on hairline
gridlines, text never wears a series color, and differences diverge blue to red
because green against red is lost to color-blind readers.

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
`test_patterns.py`, `test_forecast.py`, `test_autopilot.py` and `test_replay.py`
cover what is learned, using the synthetic ledgers built in `tests/ledgers.py`.
`test_coa_outlook.py` covers the cost-of-attendance projection: year attribution,
nine- and ten-month bills, gaps, unrecorded and bundled charges, and the verdict.

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
defaults, which take priority over plan category mappings. `autopilot.resolve`
fills in every category the student has not chosen, so callers pass its rules,
not the saved ones. A category nothing is known about counts as Everyday.

Bill categories default to Commitments (shown as **Bills**); `Irregular` is shown
as **Big stuff**. Only Everyday spending is compared with the weekly line. Legacy
`reserve` keys in saved rules are ignored. Transfers and income never count.

Removing a category, account or payment method goes through `delete_choice`,
which rechecks references on the server. Unused choices are removed immediately
with an Undo (`restore_choice`); used ones need a replacement, and the client
only receives a short preview of the affected transactions.
