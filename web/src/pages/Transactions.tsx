import { useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { type DraftFields, draftOf, get, post, type Transaction } from "../api";
import { openQuickAdd } from "../App";
import { ChoiceCombo } from "../components/ChoiceCombo";
import { treatmentLabel } from "../components/budgetBits";
import { useToast } from "../components/feedback";
import { Empty, Glyph } from "../components/instrument";
import { centsToInput, dayLabel, money, parseCents, plural } from "../lib/format";
import { categoryColor } from "../lib/glyphs";
import type { TransactionType } from "../lib/quickParse";
import { useBootstrap, useRefresh } from "../queries";
import { navigate, useLocation } from "../router";

const TYPES: TransactionType[] = ["expense", "refund", "income", "transfer"];
const PAGE = 150;
const CATEGORY_DEFAULT = "Use category default";

function signed(row: Transaction): string {
  if (row.transaction_type === "refund" || row.transaction_type === "income") return `+${money(row.amount_cents)}`;
  if (row.transaction_type === "transfer") return `⇄ ${money(row.amount_cents)}`;
  return money(row.amount_cents);
}

function net(row: Transaction): number {
  if (row.transaction_type === "expense") return row.amount_cents;
  if (row.transaction_type === "refund") return -row.amount_cents;
  return 0;
}

function EditRow({
  row,
  onDone,
  onDelete,
}: {
  row: Transaction;
  onDone: () => void;
  onDelete: () => void;
}) {
  const refresh = useRefresh();
  const toast = useToast();
  const [draft, setDraft] = useState<DraftFields>(() => draftOf(row));
  const [amount, setAmount] = useState(centsToInput(row.amount_cents));
  const [busy, setBusy] = useState(false);
  const cents = parseCents(amount);
  const valid = cents !== null && cents > 0 && draft.description.trim() && draft.transaction_date;
  const set = <K extends keyof DraftFields>(key: K, value: DraftFields[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  async function save() {
    if (!valid || cents === null) return;
    setBusy(true);
    try {
      await post("/api/transactions/edit", {
        id: row.id,
        before: draftOf(row),
        after: { ...draft, amount_cents: cents, description: draft.description.trim() },
      });
      await refresh();
      toast.show("Saved.");
      onDone();
    } catch (error) {
      toast.error(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="tx-edit stack"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onDone();
        }
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          void save();
        }
      }}
    >
      <div className="form-grid">
        <label className="field">
          <span>Date</span>
          <input type="date" value={draft.transaction_date} onChange={(event) => set("transaction_date", event.target.value)} />
        </label>
        <label className="field">
          <span>Amount</span>
          <input
            inputMode="decimal"
            value={amount}
            aria-invalid={cents === null || cents <= 0}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label className="field">
          <span>Type</span>
          <select value={draft.transaction_type} onChange={(event) => set("transaction_type", event.target.value as TransactionType)}>
            {TYPES.map((type) => (
              <option key={type}>{type}</option>
            ))}
          </select>
        </label>
        <label className="field wide">
          <span>Description</span>
          <input autoFocus value={draft.description} onChange={(event) => set("description", event.target.value)} />
        </label>
        <ChoiceCombo kind="category" label="Category" value={draft.category} onChange={(value) => set("category", value)} />
        <ChoiceCombo
          kind="payment_method"
          label="Paid with"
          value={draft.payment_method}
          onChange={(value) => set("payment_method", value)}
        />
        <ChoiceCombo kind="account" label="Account" value={draft.account} onChange={(value) => set("account", value)} />
        <label className="field">
          <span>Merchant</span>
          <input value={draft.merchant} onChange={(event) => set("merchant", event.target.value)} />
        </label>
        <label className="field wide">
          <span>Notes</span>
          <input value={draft.notes} onChange={(event) => set("notes", event.target.value)} />
        </label>
      </div>
      <div className="row between">
        <button type="button" className="btn danger small" onClick={onDelete}>
          Delete
        </button>
        <div className="row">
          <span className="tiny dim">esc to cancel · ⌘↵ to save</span>
          <button type="button" className="btn ghost" onClick={onDone}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={!valid || busy}>
            Save
          </button>
        </div>
      </div>
    </form>
  );
}

export function Transactions() {
  const { params } = useLocation();
  const bootstrap = useBootstrap();
  const refresh = useRefresh();
  const toast = useToast();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [editing, setEditing] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [limit, setLimit] = useState(PAGE);
  const [bulkCategory, setBulkCategory] = useState("");
  const [bulkTreatment, setBulkTreatment] = useState("");
  const list = useRef<HTMLDivElement>(null);

  const queryString = params.toString();
  const query = useQuery({
    queryKey: ["transactions", queryString],
    queryFn: () => get<{ rows: Transaction[]; total: number }>(`/api/transactions?${queryString}`),
    placeholderData: (previous) => previous,
  });

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    const text = next.toString();
    navigate(text ? `/transactions?${text}` : "/transactions", { replace: true });
    setLimit(PAGE);
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((params.get("q") ?? "") !== search) setParam("q", search.trim());
    }, 220);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const rows = useMemo(() => query.data?.rows ?? [], [query.data]);
  const shown = rows.slice(0, limit);
  const groups = useMemo(() => {
    const map = new Map<string, Transaction[]>();
    for (const row of shown) {
      const list = map.get(row.transaction_date) ?? [];
      list.push(row);
      map.set(row.transaction_date, list);
    }
    return [...map.entries()];
  }, [shown]);

  const filtered = ["q", "start", "end", "category", "type", "account"].some((key) => params.get(key));
  const total = rows.reduce((sum, row) => sum + net(row), 0);
  const chosen = rows.filter((row) => selected.has(row.id));
  const today = bootstrap.data?.today;

  async function remove(ids: string[]) {
    try {
      const result = await post<{ deleted: number; rows: Transaction[] }>("/api/transactions/delete", { ids });
      setSelected(new Set());
      setEditing(null);
      await refresh();
      toast.show(`Deleted ${plural(result.deleted, "transaction")}.`, {
        action: {
          label: "Undo",
          run: async () => {
            await post("/api/transactions/restore", {
              rows: result.rows.map((row) => ({ ...draftOf(row), id: row.id, created_at: row.created_at ?? null })),
            });
            await refresh();
          },
        },
      });
    } catch (error) {
      toast.error(error);
    }
  }

  async function bulkSetCategory(category: string) {
    if (!category || !chosen.length) return;
    try {
      await post("/api/transactions/batch", {
        changes: chosen.map((row) => ({ id: row.id, before: draftOf(row), after: { ...draftOf(row), category } })),
      });
      setBulkCategory("");
      await refresh();
      toast.show(`Moved ${plural(chosen.length, "transaction")} to ${category}.`);
    } catch (error) {
      toast.error(error);
    }
  }

  async function bulkSetTreatment(treatment: string) {
    if (!treatment || !chosen.length) return;
    try {
      await post("/api/spending-rules/transactions", { ids: chosen.map((row) => row.id), treatment });
      setBulkTreatment("");
      await refresh();
      toast.show(
        treatment === CATEGORY_DEFAULT
          ? `${plural(chosen.length, "transaction")} back to their category default.`
          : `Counted ${plural(chosen.length, "transaction")} as ${treatmentLabel(treatment).toLowerCase()}.`,
      );
    } catch (error) {
      toast.error(error);
    }
  }

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function onRowKey(event: KeyboardEvent<HTMLDivElement>, row: Transaction) {
    const items = [...(list.current?.querySelectorAll<HTMLElement>(".tx-row") ?? [])];
    const at = items.indexOf(event.currentTarget);
    if (event.key === "ArrowDown" || event.key === "j") {
      event.preventDefault();
      items[at + 1]?.focus();
    } else if (event.key === "ArrowUp" || event.key === "k") {
      event.preventDefault();
      items[at - 1]?.focus();
    } else if (event.key === "Enter" || event.key === "e") {
      event.preventDefault();
      setEditing(row.id);
    } else if (event.key === " " || event.key === "x") {
      event.preventDefault();
      toggle(row.id);
    } else if ((event.key === "Delete" || event.key === "Backspace") && !event.repeat) {
      event.preventDefault();
      void remove(selected.size ? [...selected] : [row.id]);
    }
  }

  const choices = bootstrap.data;
  return (
    <div className="stack loose">
      <div className="page-head">
        <div>
          <h1>Transactions</h1>
          <p>
            {query.data
              ? filtered
                ? `${plural(rows.length, "match", "matches")} · net ${money(total)}`
                : `${plural(query.data.total, "transaction")} · ↑↓ move · ↵ edit · x select`
              : "Loading…"}
          </p>
        </div>
      </div>

      <div className="card">
        <div className="filters">
          <label className="field">
            <span>Search</span>
            <input
              type="search"
              placeholder="description, merchant, notes"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label className="field">
            <span>From</span>
            <input type="date" value={params.get("start") ?? ""} onChange={(event) => setParam("start", event.target.value)} />
          </label>
          <label className="field">
            <span>To</span>
            <input type="date" value={params.get("end") ?? ""} onChange={(event) => setParam("end", event.target.value)} />
          </label>
          <label className="field">
            <span>Category</span>
            <select value={params.get("category") ?? ""} onChange={(event) => setParam("category", event.target.value)}>
              <option value="">All</option>
              {choices?.categories.map((item) => (
                <option key={item.name}>{item.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Type</span>
            <select value={params.get("type") ?? ""} onChange={(event) => setParam("type", event.target.value)}>
              <option value="">All</option>
              {TYPES.map((type) => (
                <option key={type}>{type}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn ghost"
            disabled={!filtered}
            onClick={() => {
              setSearch("");
              navigate("/transactions", { replace: true });
            }}
          >
            Clear
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: 0 }} ref={list}>
        {query.isError ? (
          <Empty title="Couldn't load transactions">
            <p>{query.error instanceof Error ? query.error.message : ""}</p>
          </Empty>
        ) : !query.data ? (
          <div className="empty">Loading…</div>
        ) : !rows.length ? (
          <Empty title={filtered ? "No matches" : "No transactions yet"}>
            <p>{filtered ? "Try fewer filters." : "Press ⌘K to add one, or import a CSV."}</p>
            {filtered ? null : (
              <button type="button" className="btn primary" onClick={() => openQuickAdd()}>
                + Add a transaction
              </button>
            )}
          </Empty>
        ) : (
          groups.map(([date, items]) => (
            <div key={date} role="group" aria-label={dayLabel(date, today)}>
              <div className="tx-day">
                <span>{dayLabel(date, today)}</span>
                <span className="num">{money(items.reduce((sum, row) => sum + net(row), 0))}</span>
              </div>
              {items.map((row) => (
                <div key={row.id}>
                  <div
                    className={`tx-row ${selected.has(row.id) ? "selected" : ""}`}
                    tabIndex={0}
                    aria-label={`${row.description}, ${signed(row)}, ${row.category}`}
                    aria-expanded={editing === row.id}
                    onClick={() => setEditing(editing === row.id ? null : row.id)}
                    onKeyDown={(event) => onRowKey(event, row)}
                  >
                    <input
                      type="checkbox"
                      className="check-input"
                      aria-label={`Select ${row.description}`}
                      checked={selected.has(row.id)}
                      onClick={(event) => event.stopPropagation()}
                      onChange={() => toggle(row.id)}
                    />
                    <Glyph category={row.category} small />
                    <span className="tx-main">
                      <span className="title">{row.description}</span>
                      <span className="meta">
                        <span style={{ color: categoryColor(row.category) }}>{row.category}</span>
                        {row.payment_method ? ` · ${row.payment_method}` : ""}
                        {row.account && row.account !== row.payment_method ? ` · ${row.account}` : ""}
                        {row.notes ? ` · ${row.notes}` : ""}
                      </span>
                    </span>
                    <span className="row tx-tags" style={{ gap: 6 }}>
                      {row.spending_treatment && row.spending_treatment !== "Everyday" && row.transaction_type === "expense" ? (
                        <span className="tag">{treatmentLabel(row.spending_treatment).toLowerCase()}</span>
                      ) : null}
                      {row.transaction_type !== "expense" ? <span className="tag">{row.transaction_type}</span> : null}
                    </span>
                    <span className={`tx-amount ${row.transaction_type}`}>{signed(row)}</span>
                  </div>
                  {editing === row.id ? (
                    <EditRow row={row} onDone={() => setEditing(null)} onDelete={() => void remove([row.id])} />
                  ) : null}
                </div>
              ))}
            </div>
          ))
        )}
        {rows.length > limit ? (
          <div className="row" style={{ justifyContent: "center", padding: 18 }}>
            <button type="button" className="btn" onClick={() => setLimit((value) => value + PAGE)}>
              Show {Math.min(PAGE, rows.length - limit)} more
            </button>
          </div>
        ) : null}
      </div>

      {chosen.length ? (
        <div className="bulkbar" role="toolbar" aria-label="Selected transactions">
          <span className="small">
            <b style={{ color: "var(--accent)" }}>{chosen.length}</b> selected ·{" "}
            {money(chosen.reduce((sum, row) => sum + net(row), 0))}
          </span>
          <select aria-label="Set category" value={bulkCategory} onChange={(event) => void bulkSetCategory(event.target.value)}>
            <option value="">Category…</option>
            {choices?.categories.map((item) => (
              <option key={item.name}>{item.name}</option>
            ))}
          </select>
          <select
            aria-label="Count as"
            value={bulkTreatment}
            onChange={(event) => void bulkSetTreatment(event.target.value)}
          >
            <option value="">Count as…</option>
            {choices?.treatments.map((item) => (
              <option key={item} value={item}>
                {treatmentLabel(item)}
              </option>
            ))}
            <option>{CATEGORY_DEFAULT}</option>
          </select>
          <button type="button" className="btn danger small" onClick={() => void remove([...selected])}>
            Delete
          </button>
          <button type="button" className="btn ghost small" onClick={() => setSelected(new Set())}>
            Clear
          </button>
        </div>
      ) : null}
    </div>
  );
}
