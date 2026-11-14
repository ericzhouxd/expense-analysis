# 記帳 user guide

## Starting the application

From the project directory, the first time (and after updating the code):

```bash
uv sync --all-groups
npm --prefix web ci
npm --prefix web run build
```

Then start it:

```bash
uv run expense-app
```

It opens <http://127.0.0.1:8765>. The server listens only on the local loopback
interface. Stop it with Ctrl+C.

### Quick add

Press **⌘K** (Ctrl+K on Windows/Linux), **N**, or the **+** button and type one line:

```text
12.50 chipotle lunch yesterday apple pay
45 #groceries trader joes fri note: split with roommate
refund 18 target 3 days ago
```

The palette shows how it read the line: amount, date, category, payment method,
and account. Click any field to correct it, or pick a category chip. **Enter**
saves and keeps the palette open for the next receipt; **⌘Enter** saves and
closes; **Esc** closes. Each saved line has an **Undo** until you close the palette.
If it looks like a duplicate, press Enter again to save it anyway.

Words the parser understands:

- Dates: `today`, `yesterday`, weekdays (`fri`, `last tue`), `nov 3`, `11/3`,
  `2026-11-03`, `3 days ago`
- Types: `refund`, `income`/`paycheck`, `transfer`
- Categories: `#tag` or `@tag` (partial names work), otherwise your keyword rules
  and past merchants
- Payment and account names from Settings, for example `apple pay` or `from checking`
- `note:` followed by anything

### Keyboard

- **1–6** switch pages (Overview, Transactions, Budgets, Insights, Import / Export,
  Settings)
- On Transactions: **↑/↓** or **j/k** move, **Enter** edits, **x** or **Space**
  selects, **Delete** deletes (with Undo), **⌘Enter** saves an edit, **Esc** cancels

## Pages

The top bar (or the bottom tabs on a phone) has six pages:

- **Overview**: the LED panel shows what you have spent this week and this
  month, each against the same days before, with the pace meter, a day-by-day
  dot calendar, where the money went, bills, the latest entries, and week by
  week and month by month.
  Click a calendar day or a category to jump to those transactions.
- **Transactions**: every entry grouped by day, with search and filters.
- **Budgets**: this quarter's weeks against your weekly line, bills and big stuff.
- **Insights**: what changed, unusual purchases, the monthly trend with a
  forecast, repeat charges and school-term totals.
- **Import / Export**: CSV preview and import, and a full CSV backup.
- **Settings**: categories, accounts, payment methods, keyword rules, privacy and
  the school calendar.

Search on **Transactions** covers description, merchant, notes, category, account
and payment method, and an amount such as `12.99` finds that exact amount.
Filters apply only to the list: Overview, Insights, Budgets and the CSV backup
always use the full ledger.

## Adding and editing transactions

Quick add (above) is the fastest way in. Amounts are always positive; the type
decides how an amount counts:

- `expense` increases spending and reduces cash flow.
- `refund` reduces spending and increases cash flow.
- `income` increases cash flow without counting as spending.
- `transfer` is recorded but excluded from spending and cash flow.

Dates before 1900 or more than a year in the future are treated as typos and
rejected.

On **Transactions**, click a row (or press **Enter**) to edit it in place, then
**Save** or **⌘Enter**. Select several rows with their checkboxes, **x** or
**Space**, then use the bar at the bottom to set a category, choose how they
count in the budget, or delete them. Deletes show an **Undo**. An edit that
would create a duplicate, or that targets a row changed elsewhere, is refused
and nothing is saved.

Category, account and payment-method fields accept new names: type one and choose
**+ name**. New choices become available everywhere.

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
| Payment method | `Payment Method`, `Payment_Method`, `Method` |
| Merchant | `Merchant` |
| Type | `Type`, `Transaction_Type` |
| Notes | `Notes` |

Header matching ignores case, spaces, hyphens, and underscores, so a backup
exported by this app imports again unchanged (and every row is recognised as a
duplicate). The preview identifies invalid rows and duplicates; a row with more
values than the header, usually an unquoted comma, is marked invalid rather than
guessed.

Use **How are amounts signed?** for rows without a Type column. By default a
negative amount is a refund. Many bank exports show purchases as negative numbers
instead: choose a bank-style option so negatives become expenses and positives
become refunds or income. Check the preview's Type column before importing.
Unknown categories become `Uncategorized` unless a category rule or your merchant
history matches. After importing, the page confirms the counts and clears the file.

The equivalent command-line import uses the same categories, rules, and merchant
history as the app:

```bash
uv run expense-import /path/to/transactions.csv
# Bank-style signs: negatives are expenses, positives are refunds (or `income`)
uv run expense-import --negative-expenses refund /path/to/transactions.csv
```

## Budgets

The budget is a **weekly line** for everyday spending, laid over the real UCLA
calendar. There is no monthly allowance to plan and nothing to fill in before it
works.

**The line.** By default it is UCLA's own estimate of everyday costs (food,
transportation and personal) for your housing type, divided across the
38 weeks of the school year. Off-campus, the 2026–27 estimate is $11,341, about
$298 a week. If you would rather use your own number, open **Budgets → Settings**
and choose **My own amount**; UCLA's estimate then stays on the chart as a blue
reference line. Figures come from [UCLA Financial Aid](https://financialaid.ucla.edu/go/coa).

**Every Monday starts fresh.** Each Monday–Sunday week gets the same line. What
you do not spend is counted as **saved**, not carried into next week, so a cheap
week never turns into permission for an expensive one. Going over shows the
amount in coral and is likewise not taken out of next week. The total saved so
far this term is shown on the Budget page and on the Overview.

**Real school weeks.** Weeks follow the [UCLA Registrar's calendar](https://registrar.ucla.edu/calendars/annual-academic-calendar),
not calendar months. A quarter is Week 0 (the days before the first Monday of
instruction, when classes start on a Thursday), Weeks 1–10 and finals week.
Winter break, spring break and summer appear as their own periods with the same
line. Use the arrows at the top of the Budget page to look at earlier terms.
Dates outside the stored calendar fall back to plain months. **Settings → School
calendar** lists the quarter dates the app uses.

**Bills and big stuff stay outside the line.**

- **Bills** are fixed costs on a schedule: monthly (on a day of the month), each
  quarter (due the first day of the quarter) or once (on a date). Add them under
  **Budgets → Settings → Bills**, with the transaction categories they are paid
  under, such as Rent or Tuition (the editor suggests categories you already
  use and warns about one no transaction has). A bill shows as **paid** once
  purchases in its categories come to about its amount (within 10%) near the
  due date, and **partly paid** when less has gone out. A monthly bill counts
  the payments closest to its own due date, so rent paid on the 30th settles
  the 1st. Bills due within a week are marked; unpaid ones past their due date
  say **no payment yet** and come first. An old due date with nothing recorded
  goes quiet once a later one is paid. The card's corner shows how many are
  paid and how much is still to go, and a bill opens the payments behind it.
  Without bills set up, the Overview lists repeating charges expected in the
  next two weeks instead.
- **Big stuff** is anything rare and large, like flights or a laptop. Mark a
  category or a single purchase as **Big stuff** and it is listed separately
  instead of blowing up one week.

All expenses and refunds count. Refunds reduce the week they land in. Income and
transfers never count as spending. This is a spending guide, **not a bank
balance or a promise of funding**. Settings are stored in the same ignored local
database as your transactions.

## Understanding the overview

The two big numbers are what you have spent this week and this month. Under
each is the same comparison: how much more or less that is than the same days
of last week, or the same days of last month. Below them:

- **Left this week**: the weekly line minus this week's everyday spending, with
  a per-day figure for the days left, or how far over the line you are. Next
  Monday starts fresh either way.
- **Same days last year**: this month so far against the same days a year ago.
- **Saved this term**: what finished weeks this term left unspent (or went over).
- The pace meter fills as you spend; the marker shows an even pace for today.
- **Week by week** and **Month by month** are the same chart at two scales.

Banners under the panel appear only when there is something to do, and each
links to where you do it: a bill past its due date, entries without a
category, categories whose budget treatment has not been reviewed, or possible
duplicates.

## Understanding insights

- **Spending drivers** compare categories in the reporting month with the same
  days of the previous month, or with the whole previous month once the
  reporting month is complete.
- **Recurring charges** require at least three occurrences with similar amounts
  and weekly, biweekly, monthly, every-two-months, quarterly, or yearly timing.
  Each shows when the next charge is expected, and **Possibly stopped** once it
  is more than half a cycle overdue.
- **Unusual purchases** use a robust median-based score within each category.
- **Trend** shows net spending by month with a rolling average. Point at a
  month to read it in the bar under the chart; click it (on a phone, tap twice)
  to open that month. The legend switches the average and the forecast on and
  off. The Overview's month strip and the Budgets week chart work the same way.
- **Forecast** (amber, in the trend and under **Looking ahead**) covers the rest
  of this month and the next three. The typical month is an average of your
  complete months in which each older month counts 60% as much as the one after
  it. The month in progress keeps what is already spent and adds the remaining
  days, leaning on the typical month early on and on this month's own pace
  later. It follows the school calendar: it learns what a week costs you in a
  quarter, on break and in summer, and scales each month by how many of those
  days it holds, so a month that is mostly break is not forecast like a month
  of classes. The likely range is how far that method missed when replayed over
  your past months, so it is wide when your months vary a lot. It needs two
  complete months, follows the Everyday / Everything switch, and cannot see
  one-off plans.
- **Cash flow** combines recorded income, refunds, and expenses. It and the
  **savings rate** appear only once some income has been recorded.
- **Academic periods** use exact configured dates when available, then fall back
  to configured month groups.

Recurring and anomaly results are review signals, not financial conclusions.

## Backups and privacy

Use **Import / Export** or `uv run expense-export` to create a CSV backup of every
transaction; filters never shorten a backup. The command line writes a
dated file such as `output/expenses-2026-11-09.csv`, so earlier backups are kept.
Files are UTF-8 with a byte-order mark, so Excel shows accented and Chinese text
correctly. Exported files contain private financial information and should be
stored securely.
CSV exports contain transactions only, not budget settings or category rules. For a complete local backup, use SQLite's backup command (the output
directory is Git-ignored):

```bash
sqlite3 data/expenses.sqlite3 ".backup 'output/expenses-backup.sqlite3'"
```

Choose a new filename to keep older backups. Do not publish the database or its
backup; local storage is not application-level encryption.

The active database is `data/expenses.sqlite3`. The entire `data/` and `output/`
directories are ignored by Git. The server answers only on `127.0.0.1`, makes no
network requests, and refuses changes that do not come from this app.

## Local customization

Create a private configuration file:

```bash
cp config.example.toml config.toml
```

Edit it to change categories, entry defaults, account choices, category rules, or
academic-period dates. The root `config.toml` is ignored by Git.

### Category suggestions

Category suggestions come from your keyword rules, your merchant history, and a
few starter words. Keywords match whole words, including plurals: `rent` matches
"Rent payment" but not "parent" or "Rental car", and `grocer` matches
"groceries". Longer keywords win, so `uber eats` beats `uber`. Review or remove
rules in **Settings → Auto-category rules**; removing a `config.toml` rule hides
it without editing that file. Picking a category yourself in quick add keeps it.

### Everyday spending, bills, and big stuff

Every purchase counts as one of three things:

- **Everyday**: the weekly line is about these.
- **Bills**: fixed, scheduled costs such as rent, phone and tuition. Categories
  used by a bill count as Bills automatically.
- **Big stuff**: rare, large purchases such as flights. Shown separately.

Overview and Insights default to **Everyday** spending. Choose **All** for
total spending charts; cash flow always includes all expenses and refunds on
their original dates. Month comparisons use the same days in both months (the
shorter month limits the comparison); once a month is complete, it is compared
with the whole previous month. Weekly comparisons use the same weekdays. Missing
history is not estimated.

In **Budgets → How categories count**, review the category suggestions and save
your defaults. Suggestions do not apply until saved. Unreviewed categories count
as everyday spending, with a review notice, so nothing slips out of the line.
Rules apply across all dates.

For a mixed category, select one or more purchases on **Transactions** and
choose **Count as…** to set an exception for just those. **Use category
default** removes the exception. Give related refunds the same treatment.
Changing how something counts moves it between the lists; it never removes the
cost.

### Editing categories, accounts, and payment methods

Open **Settings**. Each list has **Rename** and **×** (remove) beside every choice;
categories also switch between personal and fixed. Entering an existing name when
renaming merges the two. Renames update existing transactions and entry defaults;
category renames also update rules, spending treatments and budget mappings.

Unused choices disappear immediately with an **Undo**. A choice used by
transactions, rules, bills or entry defaults asks where to move them first;
transactions are never lost. `Uncategorized` stays reserved, and a category merge
that would create overlapping bill mappings is rejected. The same **×** (or
**Shift+Delete**) works inside any category, account or payment-method picker.
