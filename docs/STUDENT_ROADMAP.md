# From a personal tracker to a student product

## What exists now

One local student installation, one active plan, a versioned UCLA undergraduate
2026–27 estimate preset, and selectable 2024–25/2025–26/2026–27 UC entry cohorts.
Housing, residency, actual bills, coverage, target and buffer belong to the private
plan. The chosen reference is copied into it, so later published changes cannot
silently change an existing budget. Transactions are never part of the preset.

The UI uses UCLA defaults, but the reserve calculator does not import UCLA data.
This is a useful separation, not a claim that the app already supports arbitrary
universities, graduate programs, semester calendars, multiple users or accounts.

## Recommended first audience: UCLA undergraduates

1. Improve onboarding with guided rent/meal-plan/insurance questions, category
   mapping suggestions and a final review. Keep suggestions explainable and require
   confirmation before saving. Include demo data that is entirely synthetic.
2. Maintain a public, versioned catalog keyed by university, academic year,
   program, entry cohort, residency and housing. Record source, verification date,
   effective period and review status. Verify each release against UCLA's official
   fee tables; do not scrape silently on app startup. Unsupported profiles need
   an explicit custom setup, not another cohort's guessed fees.
3. Add multiple saved academic-year plans, cloning and year-end rollover previews.
   Keep prior snapshots for reproducibility. Model exact academic dates separately
   from budget months and cash due dates; handle summer enrollment explicitly.
4. Add private import/export of complete plans, restore validation and backups.
   Package a simple local launcher so other students can use their own isolated
   installation without learning Python. No bank integration is necessary for an
   initial useful release.
5. Validate the experience with a small group covering resident/nonresident,
   on-campus/off-campus/commuter, insurance waiver, transfers and twelve-month
   leases. Check keyboard use, narrow screens and understandable negative budgets.

Authoritative references:
[UCLA cost of attendance](https://financialaid.ucla.edu/go/coa) and
[UCLA tuition stability and fee descriptions](https://registrar.ucla.edu/fees-residence/fee-descriptions).
UC entry cohort is not necessarily the year a transfer student first arrived at UCLA.

## If we later offer hosted accounts

This is a separate security project. The current `st.cache_resource` database and
single active-plan row are appropriate only for a trusted local user. Merely adding
a login screen would not make the database safe for several students.

Before public hosting, introduce authenticated identities, ownership on every
transaction/plan/import/export, server-side authorization and isolated caches.
Use a tenant-scoped repository and database row-level isolation where supported;
test that user A cannot read, edit, export or delete user B's records, even with
guessed IDs or stale sessions. Add TLS, secret management, encryption at rest,
private backups, retention/deletion controls and incident monitoring that excludes
transaction descriptions and other financial content. A managed identity service
is preferable to custom passwords. UCLA SSO would require the relevant approval;
do not assume access to it.

Keep cloud use opt-in and preserve a local-only option. No current local data
should be uploaded as part of deployment, diagnostics or a demo. Choose the hosting
and storage model with the user before implementing migration or deployment.

## Other universities

Keep one tested accounting engine. Add validated school/program presets and a
calendar adapter (semester, quarter or custom periods) rather than copying the
UCLA page. Replace fixed nine-month/three-month assumptions in the current model
with explicit academic, summer and budget periods before claiming general support.
Offer custom benchmarks for unsupported institutions, labelled as user-entered.

Later analysis can add category envelopes within the everyday allowance,
cash-flow forecasts using actual aid/bill dates, explainable what-if scenarios,
seasonal spending pace, and plan-versus-actual history. Keep cash availability and
COA-based spending limits as different metrics throughout.
