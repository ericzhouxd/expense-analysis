# Security policy

## Reporting

Open a private security advisory on GitHub. Do not put real transactions,
database files, or exports in a report; describe the shape of the problem
instead.

## What this project protects

This is a single-user, local-only ledger. The threat model is small, but the data
is not:

- The SQLite database, generated exports, and `config.toml` are local files, and
  `.gitignore` excludes them. Real financial data must never be committed.
- The app has no authentication, no network ingress, and no multi-user mode. Run
  it on localhost; do not expose it on a public interface.
- CI and every commit see application code, tests, documentation, and example
  configuration only.

## Scope

In scope: data leaving the machine unexpectedly, committed secrets, CSV import
paths that execute or disclose data, and dependency vulnerabilities.

Out of scope: physical access to an unlocked machine, and the contents of a
locally configured `config.toml`.
