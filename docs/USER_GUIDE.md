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

It shows how the line was read: amount, date, category, payment method, account and
type. Click any of them to correct it. **Enter** saves and stays open for the next
receipt; **⌘Enter** saves and closes; **Esc** closes. Each saved line has an **Undo** until you close the palette.
If it looks like a duplicate, press Enter again to save it anyway.

Before you type an amount, the same box offers purchases you make often: pick one to
log it again with today's date, or type part of its name to narrow the list. A word on
its own also searches your transactions or jumps to a page (`import`, `setup`).

Words the parser understands:

- Dates: `today`, `yesterday`, weekdays (`fri`, `last tue`), `nov 3`, `11/3`,
  `2026-11-03`, `3 days ago`
- Types: `refund`, `income`/`paycheck`, `transfer`
- Categories: `#tag` or `@tag` (partial names work), otherwise your keyword rules
  and past merchants
- Payment and account names from Settings, for example `apple pay` or `from checking`
- `note:` followed by anything

### Keyboard

- **1–5** switch pages (Overview, Transactions, Budget, Insights, Settings), and **/**
  searches transactions
- In any list: **↑/↓** or the first letters choose, **Enter** picks, **Esc** closes
- In a date box: type a date (`fri`, `nov 3`), or **↓** for the calendar, then the arrow
  keys and **Enter**
- On Transactions: **↑/↓** or **j/k** move, **Enter** edits, **x** or **Space**
  selects, **Delete** deletes (with Undo), **⌘Enter** saves an edit, **Esc** cancels

## Pages

The bar at the top (or the tabs at the bottom on a phone) has five pages:

- **Overview**: what you have spent this week and this month, each against the same
  days before, with the latest purchases running along the bottom of the panel. Then
  anything that needs attention, the month day by day, where the money went, the trend
  by week or month, the latest entries and the largest purchases. Click a day, a category
  or a column to open those transactions. The arrows beside the month look at earlier ones.
- **Transactions**: every entry grouped by day, with search and filters.
- **Budget**: **Term** has this quarter's weeks against your weekly line; **School year** is the cost-of-attendance check; **Setup** is what the budget
  rests on.
- **Insights**: the monthly trend with a forecast, what changed and
  school-term totals.
- **Settings**: **Categories** (and how each counts, and auto-category rules),
  **Accounts** (with payment methods and what new entries start with), **Import & export**, and **App** (keyboard
  shortcuts, privacy and the school calendar).

Transactions search covers description, merchant, notes, category, account
and payment method, and an amount such as `12.99` finds that exact amount.
Filters apply only to the list: Overview, Insights, Budget and the CSV backup
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
count in the budget, or delete them. Click a category in the list
to change it without opening the row. Category changes and deletes show an **Undo**. An edit that
would create a duplicate, or that targets a row changed elsewhere, is refused
and nothing is saved.

**Settings → Accounts** has **New entry defaults**: the payment method, account and
type quick add starts with, and the category for a purchase nothing else sorts. The
menu beside an account or payment method also has **Make default**. What you type,
and a purchase you log again, still win. Imports are not affected.

Category, account and payment-method fields accept new names: type one and choose
**+ name**. New choices become available everywhere.

## Importing CSV files

Choose or drop a CSV under **Settings → Import & export**. The app shows a preview and
does not save anything until the import button is pressed.

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

Use **How amounts are written** for rows without a Type column. By default a
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
calendar. There is nothing to set up: the app works it out from what you have
recorded. Press the lamp beside an answer in **Budget → Setup** for the reason.

**Worked out from your records.** **Budget → Setup** lists every answer the
budget rests on, with a lamp for where it came from: lime from your records,
blue yours, amber earlier settings, unlit assumed. Press a lamp for the reason.
The answers:

- **Where you live**: rent or campus housing payments this school year.
- **Entry year, residency and health insurance**: the size of your tuition
  payments compared with UCLA's published charges. Buying your own plan, or a
  payment that includes UC SHIP, settles the insurance.
- **Bills**: charges that repeat by the month, the quarter or the year, with the
  next date each is expected.
- **How purchases count**: categories are sorted for you, and a purchase several
  times your usual one becomes big stuff.

Every answer can be overruled. Choose another one and it is yours from then on;
choose **Automatic** to give it back. If your records later disagree with your
choice, the row is tagged **Records:** with their answer instead of changing. Settings saved before the
budget was automatic are used only where your records show nothing. With no
tuition payment on record, choose your entry year and residency once.

Learning happens on this computer each time you open a page. No model or
profile is stored, and nothing is sent anywhere.

**The line.** It starts from UCLA's own estimate of everyday costs (food,
transportation and personal) for your housing type, divided across the
38 weeks of the school year. Off-campus, the 2026–27 estimate is $11,341, about
$298 a week. Every Monday it is checked against the whole year: if trips and
bills still to come would push you over the cost of attendance, the line is
lowered just enough, though never below half of UCLA's estimate. Finished weeks
keep the line they had, and UCLA's estimate stays on the chart as a
reference line. **Set my own** in Setup fixes an amount instead. Figures come from
[UCLA Financial Aid](https://financialaid.ucla.edu/go/coa).

**Every Monday starts fresh.** Each Monday–Sunday week gets the same line. What
you do not spend is counted as **saved**, not carried into next week, so a cheap
week never turns into permission for an expensive one. Going over shows the
amount in red and is likewise not taken out of next week. The total saved so
far this term is shown on the Budget page and on the Overview.

**Real school weeks.** Weeks follow the [UCLA Registrar's calendar](https://registrar.ucla.edu/calendars/annual-academic-calendar),
not calendar months. A quarter is Week 0 (the days before the first Monday of
instruction, when classes start on a Thursday), Weeks 1–10 and finals week.
Winter break, spring break and summer appear as their own periods with the same
line. Use the arrows at the top of the Budget page to look at earlier terms.
Dates outside the stored calendar fall back to plain months. **Settings → App**
lists the quarter dates the app uses.

**Bills and big stuff stay outside the line.**

- **Bills** are fixed costs on a schedule: monthly, each quarter or yearly. They
  appear once something repeats: two or three months in a row, or the same
  purchase a year apart (a plan that says it lasts a year needs only one). Rent
  and tuition count from the first payment. Under **Budget → Setup**, a bill's menu
  has **Edit**, which makes it yours, and **Not a bill**, which sets it aside;
  **Add a bill** adds one that has not
  been paid yet, or that is due **Once**. A bill counts as
  paid once purchases matching it come to about its amount (within 10%) near the
  due date. A monthly bill takes the payments closest to its own due date, so
  rent paid on the 30th settles the 1st. The Overview says so when a due date
  passes with no payment; dates the app guessed get an extra week first. An old
  due date with nothing recorded goes quiet once a later one is paid.
- **Big stuff** is anything rare and large, like flights or a laptop, kept out
  of the line instead of blowing up one week. **Settings → Categories** says from
  what amount a purchase counts as big; select it on **Transactions** to change one.

The Overview's **Largest** lists the six largest purchases of the last 30 days
(or of a finished month), Everyday or Big stuff, whichever way the Everyday /
Everything switch is set. Bills and refunds are left out.

**Will the whole year pass UCLA's cost of attendance?** **Budget → School
year** answers yes, no or too close to call, and adds up five layers,
from certain to guessed. If MyUCLA shows a different total for you, enter it
under **Budget → Setup**.

- **Recorded**: everything this school year, whatever it counts as. A cost
  belongs to the year it pays for: fall tuition, a plan labelled 26-27, books,
  the first rent and the flight to campus count when paid before Week 0, and
  summer rent does not. Monthly bills count from move-in through June.
- **Bills still due**: scheduled and not paid yet, on last year's dates when
  there are some.
- **Day-to-day ahead**: a forecast learned from your own weeks. It looks for the
  moment your spending level jumped (a move, the end of a meal plan) and learns
  only from the weeks since. How long it remembers is whatever would have
  predicted your past weeks best. Breaks have their own pace. Days with
  nothing recorded (before your first entry, after your last, or a blank week
  of classes) are estimated rather than treated as free.
- **Big stuff ahead**: your own pace and the same months of earlier years. Until
  half a year is recorded it leans on UCLA's figures for getting around and
  personal costs.
- **Not in your records**: tuition, fees, UC SHIP or housing that aid or family
  pays directly counts at UCLA's figure, so it never makes the year look cheap.
  Housing counts as missing when no rent is known and it is under a quarter of
  UCLA's figure. A BruinBill payment larger than tuition and fees is taken to
  cover the others.

**Heading for** shows the likely total on its likely range. **Max / week** is the
weekly everyday amount that stays under with room for surprises, and is what
the weekly line uses. **Odds over** is the chance of passing. The range should hold about four times in five.
Once a whole school year is on record, **Track record** shows what the page would have
said at this point of that year, what it was, and how far off that is, and the range
widens if it missed by more than it should. The Overview lights a caution tile when the
answer is over or too close to call. The figures are UCLA's published 2026–27
undergraduate estimates; this is not your financial aid award.

All expenses and refunds count. Refunds reduce the week they land in. Income and
transfers never count as spending. This is a spending guide, **not a bank
balance or a promise of funding**. Settings are stored in the same ignored local
database as your transactions.

## Understanding the overview

The two big numbers are what you have spent this week and this month. Under
each is the same comparison: ▲ more or ▼ less than the same days of last week, or
the same days of last month, whose dates follow. Below them:

- **Left** and **Per day**: the weekly line minus this week's everyday spending,
  and that spread over the days left. **Over line** takes its place past the
  line. Next Monday starts fresh either way.
- **Term saved** or **Term over**: what finished weeks this term left unspent, or
  went over by, with one light per week: sage inside the line, coral over.
- **Last year**: the same days of this month a year ago, and the change since.
- The meter fills as you spend, over a scale of the week's days. Segments past
  today turn coral. The amber figure over its end is the weekly line.
- **Trend** is the same chart by weeks or by months.

Amber and coral tiles under the panel light only when there is something to do, and each
links to where you do it: a bill past its due date, a school year heading past
UCLA's cost of attendance (or too close to call), entries without a
category, or possible duplicates.

## Understanding insights

- **What changed** compares categories in the reporting month with the same
  days of the previous month, or with the whole previous month once the
  reporting month is complete.
- **Trend** shows net spending by month with a rolling average. Point at a
  month to read it above the chart; click it (on a phone, tap twice)
  to open that month. The Overview's trend and the Budget week chart work the same way.
- **Forecast** (hatched in the trend, and under **Table**) covers the rest
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

## Backups and privacy

Use **Settings → Import & export** or `uv run expense-export` to create a CSV backup of every
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

Edit it to change categories, starting entry defaults, account choices, category rules, or
academic-period dates. The root `config.toml` is ignored by Git.

### Category suggestions

A new entry takes the first of these that answers:

1. The category you pick, a `#tag` on the line, or the purchase it repeats.
2. One of your keyword rules, in the description or else the merchant.
3. **Same name**: earlier entries called the same, whatever the date in the name.
4. **Same words**: earlier entries sharing words with it. A word used for many kinds
   of things counts for little, and most of the evidence has to agree.
5. **Same merchant**: at least two entries there, four in five of them in one category.
6. A built-in word such as `coffee`, until you have entries with it yourself.
7. The default category.

Recent entries count for more than old ones. A category you set yourself, by changing
an entry or picking against a suggestion in quick add, counts for the most and takes
over from what that name was before. In quick add, press the lamp in the category cell
for the evidence: lime is learned, blue your rule, amber a built-in word. Imports learn
the same way, after the file's own category and your rules, but use neither built-in
words nor the default category.

Keywords match whole words, including plurals: `rent` matches "Rent payment" but not
"parent" or "Rental car", and `grocer` matches "groceries". Longer keywords win, so
`uber eats` beats `uber`. Review or remove rules at the bottom of **Settings →
Categories**; removing a `config.toml` rule hides it without editing that file.

Suggestions are worked out from your ledger each time, on this computer. Only which
entries you corrected, and when, is stored.

### Everyday spending, bills, and big stuff

Every purchase counts as one of three things:

- **Everyday**: the weekly line is about these.
- **Bills**: fixed, scheduled costs such as rent, phone and tuition. Purchases
  that pay a bill count as Bills by themselves.
- **Big stuff**: rare, large purchases such as flights. Shown separately.

Overview and Insights default to **Everyday** spending. Choose **Everything**
for total spending charts; cash flow always includes all expenses and refunds on
their original dates. Month comparisons use the same days in both months (the
shorter month limits the comparison); once a month is complete, it is compared
with the whole previous month. Weekly comparisons use the same weekdays. Missing
history is not estimated.

Categories are sorted for you by their name and by how their purchases behave.
**Settings → Categories** shows the answer for each and the part of UCLA's cost of
attendance it lands in; point at one for the reason. Choose another to fix it;
**Automatic** gives it back. Choices saved before the budget was automatic are
kept as yours only where they differ from what the app used to suggest. Rules
apply across all dates.

For a mixed category, select one or more purchases on **Transactions** and
choose **Count as…** to set an exception for just those. **Use category
default** removes the exception. Give related refunds the same treatment.
Changing how something counts moves it between the lists; it never removes the
cost.

### Editing categories, accounts, and payment methods

Open **Settings → Categories** or **Accounts**. The menu beside each choice has **Rename**
and **Remove**; categories also switch between personal and fixed. Entering an existing name when
renaming merges the two. Renames update existing transactions and entry defaults;
category renames also update rules, spending treatments and budget mappings.

Unused choices disappear immediately with an **Undo**. A choice used by
transactions, rules, bills or entry defaults asks where to move them first;
transactions are never lost. `Uncategorized` stays reserved, and a category merge
that would create overlapping bill mappings is rejected. **×** (or
**Shift+Delete**) does the same inside any category, account or payment-method picker.
