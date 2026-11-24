import { useQuery } from "@tanstack/react-query";
import { type KeyboardEvent, type MouseEvent, useEffect, useMemo, useRef, useState } from "react";

import { type DraftFields, draftOf, get, post, type Transaction } from "../api";
import { treatmentLabel } from "../components/budgetBits";
import { ChoiceCombo } from "../components/ChoiceCombo";
import { useToast } from "../components/feedback";
import { Icon } from "../components/icons";
import { Glyph } from "../components/instrument";
import { DatePicker, namesOf, type Option, Select } from "../components/pickers";
import { Empty, Loading, LoadError, Menu, PageHead } from "../components/ui";
import { addDays, centsToInput, dayLabel, iso, money, parseCents, parseIso, plural, rangeLabel, shortDate } from "../lib/format";
import type { TransactionType } from "../lib/quickParse";
import { useBootstrap, useRefresh } from "../queries";
import { linkTo, navigate, openQuickAdd, useLocation } from "../router";

const TYPES: TransactionType[] = ["expense", "refund", "income", "transfer"];
const PAGE = 120;
const TYPE_OPTIONS: Option[] = TYPES.map((type) => ({ value: type, label: `${type[0]?.toUpperCase()}${type.slice(1)}` }));
const CATEGORY_DEFAULT = "Use category default";
const FILTERS = ["q", "start", "end", "category", "type", "account", "counts"] as const;

function signed(row: Transaction): string {
  if (row.transaction_type === "refund" || row.transaction_type === "income") return `+${money(row.amount_cents)}`;
  return money(row.amount_cents);
}

function net(row: Transaction): number {
  if (row.transaction_type === "expense") return row.amount_cents;
  if (row.transaction_type === "refund") return -row.amount_cents;
  return 0;
}

/** Ranges people ask for by name. */
function presets(today: string): { label: string; start: string; end: string }[] {
  const now = parseIso(today);
  const monday = addDays(now, -((now.getDay() + 6) % 7));
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return [
    { label: "This week", start: iso(monday), end: iso(addDays(monday, 6)) },
    { label: "Last week", start: iso(addDays(monday, -7)), end: iso(addDays(monday, -1)) },
    { label: "This month", start: iso(first), end: iso(new Date(now.getFullYear(), now.getMonth() + 1, 0)) },
    { label: "Last month", start: iso(previous), end: iso(addDays(first, -1)) },
    { label: "Last 90 days", start: iso(addDays(now, -89)), end: today },
  ];
}

function rangeText(start: string, end: string): string {
  if (start && end) return start === end ? shortDate(start) : rangeLabel(start, end);
  return start ? `From ${shortDate(start)}` : `Until ${shortDate(end)}`;
}

function EditRow({
  row,
  treatments,
  onDone,
  onDelete,
}: {
  row: Transaction;
  treatments: string[];
  onDone: () => void;
  onDelete: () => void;
}) {
  const refresh = useRefresh();
  const toast = useToast();
  const [draft, setDraft] = useState<DraftFields>(() => draftOf(row));
  const [amount, setAmount] = useState(centsToInput(row.amount_cents));
  const [treatment, setTreatment] = useState("");
  const [busy, setBusy] = useState(false);
  const cents = parseCents(amount);
  const valid = cents !== null && cents > 0 && draft.description.trim() && draft.transaction_date;
  const set = <K extends keyof DraftFields>(key: K, value: DraftFields[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const spends = draft.transaction_type === "expense" || draft.transaction_type === "refund";

  async function save() {
    if (!valid || cents === null) return;
    setBusy(true);
    try {
      await post("/api/transactions/edit", {
        id: row.id,
        before: draftOf(row),
        after: { ...draft, amount_cents: cents, description: draft.description.trim() },
      });
      if (treatment) await post("/api/spending-rules/transactions", { ids: [row.id], treatment });
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
      className="tx-edit"
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
      <div className={`form-grid ${spends ? "" : "short"}`}>
        <label className="field wide">
          <span>Description</span>
          <input autoFocus value={draft.description} onChange={(event) => set("description", event.target.value)} />
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
        <DatePicker label="Date" value={draft.transaction_date} onChange={(value) => set("transaction_date", value)} />
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
        <Select
          label="Type"
          value={draft.transaction_type}
          options={TYPE_OPTIONS}
          onChange={(value) => set("transaction_type", value as TransactionType)}
        />
        {spends ? (
          <Select
            label="Counts as"
            value={treatment}
            onChange={setTreatment}
            options={[
              { value: "", label: row.spending_treatment ? treatmentLabel(row.spending_treatment) : "Automatic", group: "Now" },
              ...treatments
                .filter((item) => item !== row.spending_treatment)
                .map((item) => ({ value: item, label: treatmentLabel(item), group: "Change to" })),
              { value: CATEGORY_DEFAULT, label: "Automatic", group: "Change to" },
            ]}
          />
        ) : null}
        <label className="field wide">
          <span>Notes</span>
          <input value={draft.notes} onChange={(event) => set("notes", event.target.value)} />
        </label>
      </div>
      <div className="row between">
        <button type="button" className="btn ghost small danger" onClick={onDelete}>
          Delete
        </button>
        <div className="row">
          <button type="button" className="btn ghost small" onClick={onDone}>
            Cancel
          </button>
          <button type="submit" className="btn primary small" disabled={!valid || busy}>
            Save <kbd>⌘↵</kbd>
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
  const [custom, setCustom] = useState(false);
  const [more, setMore] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  /** The last row selected, where a shift-click range starts. */
  const anchor = useRef<string | null>(null);

  // "Counts as" is worked out per row, so it filters the rows the server sent.
  const counts = params.get("counts") ?? "";
  const sent = new URLSearchParams(params);
  sent.delete("counts");
  const queryString = sent.toString();
  const query = useQuery({
    queryKey: ["transactions", queryString],
    queryFn: () => get<{ rows: Transaction[]; total: number }>(`/api/transactions?${queryString}`),
    placeholderData: (previous) => previous,
  });

  function setParams(next: Record<string, string>) {
    const value = new URLSearchParams(params);
    for (const [key, item] of Object.entries(next)) {
      if (item) value.set(key, item);
      else value.delete(key);
    }
    const text = value.toString();
    navigate(text ? `/transactions?${text}` : "/transactions", { replace: true });
    setLimit(PAGE);
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((params.get("q") ?? "") !== search.trim()) setParams({ q: search.trim() });
    }, 220);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // A link from elsewhere (the ⌘K panel, a back button) can change the search too.
  const linked = params.get("q") ?? "";
  useEffect(() => {
    setSearch((current) => (current.trim() === linked ? current : linked));
  }, [linked]);

  const rows = useMemo(
    () =>
      (query.data?.rows ?? []).filter(
        (row) =>
          !counts ||
          (row.spending_treatment === counts &&
            (row.transaction_type === "expense" || row.transaction_type === "refund")),
      ),
    [query.data, counts],
  );
  const shown = rows.slice(0, limit);
  const groups = useMemo(() => {
    const map = new Map<string, Transaction[]>();
    for (const row of shown) {
      const items = map.get(row.transaction_date) ?? [];
      items.push(row);
      map.set(row.transaction_date, items);
    }
    return [...map.entries()];
  }, [shown]);

  // Older rows appear as the end of the list comes into view.
  const hasMore = rows.length > limit;
  useEffect(() => {
    const element = end.current;
    if (!element || !hasMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setLimit((value) => value + PAGE);
      },
      { rootMargin: "600px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasMore, limit]);

  const start = params.get("start") ?? "";
  const until = params.get("end") ?? "";
  const filtered = FILTERS.some((key) => params.get(key));
  const total = rows.reduce((sum, row) => sum + net(row), 0);
  const chosen = rows.filter((row) => selected.has(row.id));
  const choices = bootstrap.data;
  const names = useMemo(() => (choices?.categories ?? []).map((item) => item.name), [choices]);
  const today = choices?.today;
  const ranges = today ? presets(today) : [];
  const preset = ranges.find((item) => item.start === start && item.end === until);
  const dated = Boolean(start || until);

  async function remove(ids: string[]) {
    try {
      const result = await post<{ deleted: number; rows: Transaction[] }>("/api/transactions/delete", { ids });
      setSelected(new Set());
      setEditing(null);
      await refresh();
      toast.show(`Deleted ${plural(result.deleted, "transaction")}.`, {
        actions: [
          {
            label: "Undo",
            run: async () => {
              await post("/api/transactions/restore", {
                rows: result.rows.map((row) => ({ ...draftOf(row), id: row.id, created_at: row.created_at ?? null })),
              });
              await refresh();
            },
          },
        ],
      });
    } catch (error) {
      toast.error(error);
    }
  }

  /** Save a category at once, with a way back and, for new merchants, a way to make it stick. */
  async function categorize(items: Transaction[], category: string) {
    const changed = items.filter((row) => row.category !== category);
    if (!category || !changed.length) return;
    const changes = changed.map((row) => ({ id: row.id, before: draftOf(row), after: { ...draftOf(row), category } }));
    const only = changed.length === 1 ? changed[0] : undefined;
    const unsorted = ["Uncategorized", bootstrap.data?.defaults.category];
    const word = only && unsorted.includes(only.category) ? only.merchant || only.description : "";
    try {
      await post("/api/transactions/batch", { changes });
      await refresh();
      toast.show(only ? `Moved to ${category}.` : `Moved ${plural(changed.length, "transaction")} to ${category}.`, {
        actions: [
          word && word.length <= 28 && category !== "Uncategorized"
            ? {
                label: `Always for “${word}”`,
                run: async () => {
                  await post("/api/keyword-rules", { keyword: word, category });
                  await refresh();
                  toast.show(`New entries with “${word}” will go to ${category}.`);
                },
              }
            : null,
          {
            label: "Undo",
            run: async () => {
              await post("/api/transactions/batch", {
                changes: changes.map((item) => ({ id: item.id, before: item.after, after: item.before })),
              });
              await refresh();
            },
          },
        ],
      });
    } catch (error) {
      toast.error(error);
    }
  }

  async function countAs(treatment: string) {
    if (!treatment || !chosen.length) return;
    try {
      await post("/api/spending-rules/transactions", { ids: chosen.map((row) => row.id), treatment });
      await refresh();
      toast.show(
        treatment === CATEGORY_DEFAULT
          ? `${plural(chosen.length, "transaction")} counted automatically again.`
          : `${plural(chosen.length, "transaction")} now ${chosen.length === 1 ? "counts" : "count"} as ${treatmentLabel(treatment).toLowerCase()}.`,
      );
    } catch (error) {
      toast.error(error);
    }
  }

  /** Every category, with the row's own even if it has since been removed. */
  function categoryOptions(current: string): Option[] {
    if (current === "Uncategorized") {
      return [
        { value: current, label: "Choose category" },
        ...namesOf(names.filter((name) => name !== current), true),
      ];
    }
    return namesOf(names.includes(current) ? names : [current, ...names], true);
  }

  function toggle(id: string, range = false) {
    setSelected((current) => {
      const next = new Set(current);
      const ids = rows.map((row) => row.id);
      const from = anchor.current ? ids.indexOf(anchor.current) : -1;
      const to = ids.indexOf(id);
      const on = !next.has(id);
      const touched = range && from >= 0 ? ids.slice(Math.min(from, to), Math.max(from, to) + 1) : [id];
      for (const item of touched) {
        if (on) next.add(item);
        else next.delete(item);
      }
      return next;
    });
    anchor.current = id;
  }

  function onRowKey(event: KeyboardEvent<HTMLDivElement>, row: Transaction) {
    if (event.target !== event.currentTarget) return;
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
      toggle(row.id, event.shiftKey);
    } else if (event.key === "Escape" && selected.size) {
      setSelected(new Set());
    } else if ((event.key === "Delete" || event.key === "Backspace") && !event.repeat) {
      event.preventDefault();
      void remove(selected.size ? [...selected] : [row.id]);
    }
  }

  function closeEditor(id: string) {
    setEditing(null);
    // Back to the row, so the keyboard carries on from there.
    window.setTimeout(() => document.getElementById(`tx-${id}`)?.focus(), 0);
  }

  function onRowClick(event: MouseEvent<HTMLDivElement>, row: Transaction) {
    if (event.target instanceof HTMLElement && event.target.closest("button, input")) return;
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      window.getSelection()?.removeAllRanges();
      toggle(row.id, event.shiftKey);
      return;
    }
    setEditing(editing === row.id ? null : row.id);
  }

  return (
    <>
      <PageHead
        title="Transactions"
        meta={
          query.data
            ? filtered
              ? `${rows.length.toLocaleString("en-US")} / ${query.data.total.toLocaleString("en-US")} · ${money(total)}`
              : query.data.total.toLocaleString("en-US")
            : undefined
        }
      >
        <Menu
          label="Import and export"
          small={false}
          items={[
            { label: "Import a CSV", icon: "upload", href: "/settings/data" },
            { label: "Export everything", icon: "download", href: "/api/export.csv", download: true },
          ]}
        />
      </PageHead>

      <div className="card filters" role="search">
        <span className="search">
          <Icon name="search" />
          <input
            type="search"
            className="input"
            aria-label="Search transactions"
            placeholder="Search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                if (search) setSearch("");
                else event.currentTarget.blur();
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                list.current?.querySelector<HTMLElement>(".tx-row")?.focus();
              }
            }}
          />
          <kbd>/</kbd>
        </span>
        <Select
          aria-label="Dates"
          className={dated ? "active" : ""}
          value={custom ? "custom" : preset ? preset.label : dated ? "other" : ""}
          options={[
            { value: "", label: "Any date" },
            ...namesOf(ranges.map((item) => item.label)),
            ...(dated && !preset ? [{ value: "other", label: rangeText(start, until) }] : []),
            { value: "custom", label: "Custom dates…" },
          ]}
          onChange={(value) => {
            setCustom(value === "custom");
            if (value === "custom" || value === "other") return;
            const range = ranges.find((item) => item.label === value);
            setParams({ start: range?.start ?? "", end: range?.end ?? "" });
          }}
        />
        <Select
          aria-label="Category"
          className={params.get("category") ? "active" : ""}
          value={params.get("category") ?? ""}
          options={[{ value: "", label: "Any category" }, ...namesOf(names, true)]}
          onChange={(value) => setParams({ category: value })}
        />
        {more || counts || params.get("type") || params.get("account") ? (
          <>
            <Select
              aria-label="Counts as"
              className={counts ? "active" : ""}
              value={counts}
              options={[
                { value: "", label: "Any kind" },
                ...(choices?.treatments ?? []).map((item) => ({ value: item, label: treatmentLabel(item) })),
              ]}
              onChange={(value) => setParams({ counts: value })}
            />
            <Select
              aria-label="Type"
              className={params.get("type") ? "active" : ""}
              value={params.get("type") ?? ""}
              options={[{ value: "", label: "Any type" }, ...TYPE_OPTIONS]}
              onChange={(value) => setParams({ type: value })}
            />
            <Select
              aria-label="Account"
              className={params.get("account") ? "active" : ""}
              value={params.get("account") ?? ""}
              options={[{ value: "", label: "Any account" }, ...namesOf(choices?.accounts ?? [])]}
              onChange={(value) => setParams({ account: value })}
            />
          </>
        ) : (
          <button type="button" className="btn ghost" onClick={() => setMore(true)}>
            More filters
          </button>
        )}
        {custom ? (
          <span className="custom-dates">
            <DatePicker aria-label="From" placeholder="From" value={start} onChange={(value) => setParams({ start: value })} />
            <span className="dim">to</span>
            <DatePicker aria-label="To" placeholder="To" value={until} onChange={(value) => setParams({ end: value })} />
          </span>
        ) : null}
        {filtered ? (
          <button
            type="button"
            className="btn ghost"
            onClick={() => {
              setSearch("");
              setCustom(false);
              setMore(false);
              navigate("/transactions", { replace: true });
            }}
          >
            Clear
          </button>
        ) : null}
      </div>

      <div className="tx-list" ref={list}>
        {!query.data ? (
          query.isError ? (
            <LoadError what="transactions" error={query.error} retry={() => void query.refetch()} />
          ) : (
            <Loading />
          )
        ) : !rows.length ? (
          filtered ? (
            <Empty title="Nothing matches">
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setSearch("");
                  navigate("/transactions", { replace: true });
                }}
              >
                Clear filters
              </button>
            </Empty>
          ) : (
            <Empty title="No transactions yet">
              <div className="row">
                <button type="button" className="btn primary" onClick={() => openQuickAdd()}>
                  Add a transaction
                </button>
                <a className="btn" {...linkTo("/settings/data")}>
                  Import a CSV
                </a>
              </div>
            </Empty>
          )
        ) : (
          <div className="card tx-card">
          {groups.map(([date, items]) => (
            <div key={date} className="tx-group" role="group" aria-label={dayLabel(date, today)}>
              <div className="tx-day">
                <span>{dayLabel(date, today)}</span>
                <span>{money(items.reduce((sum, row) => sum + net(row), 0))}</span>
              </div>
              {items.map((row) => (
                <div key={row.id}>
                  <div
                    id={`tx-${row.id}`}
                    className={`tx-row ${selected.has(row.id) ? "selected" : ""} ${editing === row.id ? "open" : ""}`}
                    tabIndex={0}
                    aria-label={`${row.description}, ${signed(row)}, ${row.category}`}
                    aria-expanded={editing === row.id}
                    onClick={(event) => onRowClick(event, row)}
                    onKeyDown={(event) => onRowKey(event, row)}
                  >
                    <input
                      type="checkbox"
                      className="check-input"
                      tabIndex={-1}
                      aria-label={`Select ${row.description}`}
                      checked={selected.has(row.id)}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggle(row.id, event.shiftKey);
                      }}
                      onChange={() => undefined}
                    />
                    <Glyph category={row.category} />
                    <span className="tx-main">
                      <span className="title truncate">
                        {row.description}
                        {row.merchant && row.merchant.toLowerCase() !== row.description.toLowerCase() ? (
                          <span className="dim"> {row.merchant}</span>
                        ) : null}
                      </span>
                      <span className="meta">
                        <Select
                          look="text"
                          className={row.category === "Uncategorized" ? "missing" : ""}
                          aria-label={`Category of ${row.description}`}
                          tabIndex={-1}
                          value={row.category}
                          placeholder="Choose category"
                          options={categoryOptions(row.category)}
                          onChange={(value) => void categorize([row], value)}
                        />
                        <span className="truncate">
                          {[row.payment_method, row.account, row.notes].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                    </span>
                    <span className="tx-tags">
                      {row.spending_treatment &&
                      row.spending_treatment !== "Everyday" &&
                      row.transaction_type === "expense" ? (
                        <span className="tag">{treatmentLabel(row.spending_treatment)}</span>
                      ) : null}
                      {row.transaction_type !== "expense" ? (
                        <span className={`tag ${row.transaction_type === "transfer" ? "" : "ok"}`}>
                          {row.transaction_type}
                        </span>
                      ) : null}
                    </span>
                    <span className={`tx-amount ${row.transaction_type}`}>{signed(row)}</span>
                  </div>
                  {editing === row.id ? (
                    <EditRow
                      row={row}
                      treatments={choices?.treatments ?? []}
                      onDone={() => closeEditor(row.id)}
                      onDelete={() => void remove([row.id])}
                    />
                  ) : null}
                </div>
              ))}
            </div>
          ))}
          </div>
        )}
        {hasMore ? (
          <div ref={end} className="tx-more">
            <button type="button" className="btn" onClick={() => setLimit((value) => value + PAGE)}>
              Show older
            </button>
          </div>
        ) : null}
      </div>

      {chosen.length ? (
        <div className="bulkbar" role="toolbar" aria-label="Selected transactions">
          <span className="nowrap">
            <b>{chosen.length}</b> selected <span className="dim">· {money(chosen.reduce((sum, row) => sum + net(row), 0))}</span>
          </span>
          {filtered && chosen.length < rows.length ? (
            <button
              type="button"
              className="btn ghost small"
              onClick={() => setSelected(new Set(rows.map((row) => row.id)))}
            >
              Select all {rows.length}
            </button>
          ) : null}
          <Select
            look="small"
            aria-label="Set category"
            placeholder="Category"
            value=""
            options={namesOf(names, true)}
            onChange={(value) => void categorize(chosen, value)}
          />
          <Select
            look="small"
            aria-label="Count as"
            placeholder="Count as"
            value=""
            options={[
              ...(choices?.treatments ?? []).map((item) => ({ value: item, label: treatmentLabel(item) })),
              { value: CATEGORY_DEFAULT, label: "Automatic" },
            ]}
            onChange={(value) => void countAs(value)}
          />
          <button type="button" className="btn ghost small danger" onClick={() => void remove([...selected])}>
            Delete
          </button>
          <button
            type="button"
            className="btn ghost small icon"
            aria-label="Clear selection"
            onClick={() => setSelected(new Set())}
          >
            <Icon name="close" size={8} />
          </button>
        </div>
      ) : null}
    </>
  );
}
