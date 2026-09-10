# 記帳 user guide

## Starting the application

From the project directory:

```bash
uv sync --all-groups
uv run streamlit run app.py
```

Open <http://127.0.0.1:8501>. The server listens only on the local loopback
interface.

## Navigation and filters

### Appearance

Use the **Appearance** control at the bottom of the sidebar to choose **System**,
**Light**, or **Dark**. This controls the entire application, including charts, editable
tables, forms, and textured panels. Restart the server once after upgrading from the
earlier design so the new theme configuration and bundled fonts load.

The interface uses square grids, brushed-metal headers, and dotted balance panels.
Condensed numerals emphasize amounts; Departure Mono gives labels and controls a
late-90s/early-00s interface character. Compact labels use tracked capitals while
longer descriptions remain sentence case. All three font families are served locally.
There are no remote font services, campus photos, or promotional slogans.

Charts keep their controls out of the way. Click a chart to open it fullscreen, then
click it again or press **Escape** to return to the page.
Long category charts scroll vertically inside their panels. A scrollbar on the right
keeps every category accessible without squeezing labels; legends stay interactive.

### Pages

The sidebar contains six application areas:

- **Overview** summarizes the latest personal-spending period.
- **Transactions** provides transaction entry, a readable list, and an editing table.
- **Import / Export** validates incoming CSVs and creates local backups.
- **Budgets** plans monthly and quarterly everyday spending after UCLA costs and bills.
- **Advanced insights** shows cash flow, unusual purchases, recurring charges,
  spending drivers, and academic-period comparisons.
- **Settings** describes privacy status and local configuration.

Open **Filter activity** in the sidebar to limit the current view by date,
keyword, category, transaction type, or account. Filters affect the dashboard,
transaction list, insights, and exported selection.

## Adding and editing transactions

Open **Transactions** and select **Add transaction** for normal entry. Enter advances
through the form fields; Enter from **Notes** saves once the required values are filled.
Shift+Enter adds a new line in Notes. After saving, select **View** in the confirmation
box to reveal and highlight the new transaction, even when the active filters exclude it.
Category, account, and payment-method fields accept new choices. Type a name and
press Enter to see **Add new …?**; Enter again adds it, and Escape cancels.
The same confirmation applies to filters and editable table choices. Custom choices
saved with a transaction or spending plan become available elsewhere in the app.
Amounts are entered as positive values; the selected transaction type determines how
the amount affects spending and cash flow.

- `expense` increases spending and reduces cash flow.
- `refund` reduces spending and increases cash flow.
- `income` increases cash flow without counting as spending.
- `transfer` is recorded but excluded from spending and cash flow.

In **Transactions**, the default list view is optimized for reading. Select
**Edit table** to change multiple transactions. Use **Review changes** to check
the before/after values, then **Confirm changes** to save the batch. Marked
deletions require an explicit acknowledgement. **Discard edits / reload** restores
the saved table. Invalid amounts, missing required fields, new duplicates, and
records changed in another session block the save; the batch is saved together.
Category, account, and payment method each allow one choice per transaction.
Remove the current choice before selecting or creating its replacement.

## Importing CSV files

Upload a CSV from **Import / Export**. The app shows a preview and does not save
anything until the import button is pressed.

Recognized column names include:

| Purpose | Accepted headers |
|---|---|
| Description | `Description`, `Expense` |
| Date | `Date`, `Transaction_Date` |
| Amount | `Amount`, `Amount_Dollars` |
| Category | `Category` |
| Account | `Account`, `From`, `Source` |
| Payment method | `Payment_Method`, `Method` |
| Merchant | `Merchant` |
| Type | `Type`, `Transaction_Type` |
| Notes | `Notes` |

The preview identifies invalid rows and duplicates. Negative amounts without an
explicit type are interpreted as refunds. Unknown categories become
`Uncategorized` unless a local category rule matches.

The equivalent command-line import is:

```bash
uv run expense-import /path/to/transactions.csv
```

## Budgets

The UCLA spending plan replaces the old category-limit editor. Start by choosing
your UC entry cohort, housing benchmark and tuition residency. The first draft
uses the **2024–25 cohort** with current **2026–27 undergraduate living estimates**.
Other supported cohorts are 2025–26 and 2026–27. Estimates come from
[UCLA Financial Aid](https://financialaid.ucla.edu/go/coa), verified September 8, 2026.
Tuition includes student services; campus fees and insurance are separate.

1. Choose the first budget month and nine or twelve months of coverage.
2. Check the nine-month target. Add a separate summer target for a twelve-month
   plan; the app does not divide a nine-month COA across twelve months.
3. Enter real rent, utilities, internet, insurance and any other commitments.
   Rent and utilities start at zero because the app does not know your bills.
4. Choose each bill's cycle: monthly amount, quarterly amount, or one total for
   its coverage. First month is numbered from 1. Extend lease coverage to twelve
   months when appropriate; changing the plan length does not change bill rows.
5. Select transaction categories for each bill, or type and confirm new ones. Confirm the
   setup and save. Nothing is saved automatically.

The main calculation is:

```text
Spending target − committed costs − protected buffer = everyday allowance
Everyday allowance + carry within quarter − net everyday spending = remaining
```

Tuition, insurance and other coverage-total bills are spread over their coverage
months even if paid upfront. A quarterly bill repeats every three months from its
first coverage month. Paying a bill uses its reserve, not a second deduction.
Overruns reduce the allowance. If a finalized bill is cheaper, edit its reserve
down to release the difference; an unpaid bill is never mistaken for spare money.
Use separate, nonoverlapping bill rows for seasonal rent changes or unequal fees.
For quarter-specific tuition tracking, use a quarterly amount or separate rows
instead of the default whole-year tuition reserve.

Quarterly allowance is divided evenly across its three months, with exact-cent
rounding. The breakdown shows a smoothing adjustment where needed. Both positive
and negative monthly remaining amounts carry within a quarter; there is no
automatic carry between quarters. The last month's remaining equals the quarter's
remaining; do not sum monthly remaining figures (they include earlier balances).
Budget quarters are consecutive three-month blocks, **not official UCLA term
dates**. With the default October start, Q1 is October–December.

All expenses/refunds inside the plan count, including unknown categories and
travel. Those not matched to a commitment count as everyday spending. Income and
transfers do not change the target. Activity filters never limit the budget ledger.
Combined housing/meal-plan bills should be mapped and reserved once. If a local
`config.toml` overrides categories, add Rent, Utilities and Internet there or map
the categories you already use.

Use **Payment timing & transaction review** for tuition paid before the plan or
refunds belonging to an earlier bill cycle. Assign a budget month; the original
transaction date and other pages' cash-flow calculations remain unchanged.
Remove an override by choosing **Use transaction date**. Review **Expenses included
in this period** to check each transaction's treatment.

The weekly guide spreads remaining allowance across days left in the selected
period (up to seven days), never below zero. Future views assume no additional
unrecorded spending. This is a spending ceiling, **not a bank balance or a promise
of funding**. A waived insurance bill does not automatically lower the COA-based
target: lower the target too if that is your intended policy.

The app keeps one active local plan. Its public reference snapshot does not
silently update when tuition tables change. The old monthly category budgets
remain in SQLite for preservation but are no longer shown. Private plans and
payment allocations are stored in the same ignored database as transactions.

## Understanding the overview

The overview prioritizes four questions:

1. How much personal spending occurred in the latest period?
2. How much everyday allowance remains under the new plan?
3. How does the period compare with the previous month?
4. What is the current month-end run-rate?

The trend includes the monthly total and a three-month rolling average. “What
changed” highlights the largest category movements plus detected recurring or
unusual activity. Detailed year comparisons and fixed-versus-personal spending
remain collapsed until requested.

## Understanding advanced insights

- **Spending drivers** compare categories in the latest two months.
- **Recurring charges** require at least three occurrences with similar amounts
  and weekly, monthly, or quarterly timing.
- **Unusual purchases** use a robust median-based score within each category.
- **Cash flow** combines recorded income, refunds, and expenses.
- **Savings rate** is available only when income has been recorded.
- **Academic periods** use exact configured dates when available, then fall back
  to configured month groups.

Recurring and anomaly results are review signals, not financial conclusions.

## Backups and privacy

Use **Import / Export** or `uv run expense-export` to create a CSV backup. Exported
files contain private financial information and should be stored securely.
CSV exports contain transactions only, not the spending plan or payment
allocations. For a complete local backup, use SQLite's backup command (the output
directory is Git-ignored):

```bash
sqlite3 data/expenses.sqlite3 ".backup 'output/expenses-backup.sqlite3'"
```

Choose a new filename to keep older backups. Do not publish the database or its
backup; local storage is not application-level encryption.

The active database is `data/expenses.sqlite3`. The entire `data/` and `output/`
directories are ignored by Git. Streamlit telemetry is disabled, and the server
is configured for `127.0.0.1`.

## Local customization

Create a private configuration file:

```bash
cp config.example.toml config.toml
```

Edit it to change categories, entry defaults, account choices, category rules, or
academic-period dates. The root `config.toml` is ignored by Git.
