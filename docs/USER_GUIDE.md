# Local Spending user guide

## Starting the application

From the project directory:

```bash
uv sync --all-groups
uv run streamlit run app.py
```

Open <http://127.0.0.1:8501>. The server listens only on the local loopback
interface.

## Navigation and filters

The sidebar contains the seven application areas:

- **Overview** summarizes the latest personal-spending period.
- **Transactions** provides a readable list and an editing table.
- **Add transaction** records a new expense, refund, income item, or transfer.
- **Import / Export** validates incoming CSVs and creates local backups.
- **Budgets** stores monthly limits for personal categories.
- **Advanced insights** shows cash flow, unusual purchases, recurring charges,
  spending drivers, and academic-period comparisons.
- **Settings** describes privacy status and local configuration.

Open **Filter activity** in the sidebar to limit the current view by date,
keyword, category, transaction type, or account. Filters affect the dashboard,
transaction list, insights, and exported selection.

## Adding and editing transactions

Use **Add transaction** for normal entry. Amounts are entered as positive values;
the selected transaction type determines how the amount affects spending and cash
flow.

- `expense` increases spending and reduces cash flow.
- `refund` reduces spending and increases cash flow.
- `income` increases cash flow without counting as spending.
- `transfer` is recorded but excluded from spending and cash flow.

In **Transactions**, the default list view is optimized for reading. Select
**Edit table** to change multiple transactions. Marked deletions require a
separate confirmation before they are permanent.

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

Choose a month, enter limits for the categories you care about, and save. Progress
bars use:

- Green below 80%
- Gold from 80% through 100%
- Coral above 100%

Budgets are stored locally in the same SQLite database as transactions.

## Understanding the overview

The overview prioritizes four questions:

1. How much personal spending occurred in the latest period?
2. How much budget remains?
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
