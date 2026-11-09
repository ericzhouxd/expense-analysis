import { useMemo, useRef, useState } from "react";

import { ApiError, post, type Transaction } from "../api";
import { dayLabel, money, parseCents, centsToInput } from "../lib/format";
import { categoryColor, rgba } from "../lib/glyphs";
import { parseQuickEntry, type Role, type TransactionType } from "../lib/quickParse";
import { useBootstrap, useOverview, useRefresh, vocabularyOf } from "../queries";
import { Modal, useToast } from "./feedback";
import { Housing, Odometer } from "./instrument";

const ROLE_COLORS: Partial<Record<Role, string>> = {
  amount: "#D4F53C",
  date: "#7CB8FF",
  type: "#F2C14E",
  payment: "#C9A2FF",
  account: "#9FD39B",
  note: "#A7AF9E",
};

const ROLE_NAMES: Partial<Record<Role, string>> = {
  amount: "AMT",
  date: "DATE",
  type: "TYPE",
  category: "CAT",
  payment: "PAY",
  account: "ACCT",
};

type FieldKey =
  | "amount"
  | "date"
  | "description"
  | "category"
  | "payment_method"
  | "account"
  | "transaction_type";

const TYPES: TransactionType[] = ["expense", "refund", "income", "transfer"];

/**
 * The ⌘K palette: type one line, see it parsed live, press Enter. Every parsed
 * field can be clicked and corrected before saving; the palette stays open so a
 * whole receipt pile can be entered in a row.
 */
export function QuickAdd({ onClose, initialText = "" }: { onClose: () => void; initialText?: string }) {
  const bootstrap = useBootstrap();
  const overview = useOverview(null, "everyday");
  const refresh = useRefresh();
  const toast = useToast();
  const [text, setText] = useState(initialText);
  const [overrides, setOverrides] = useState<Partial<Record<FieldKey, string>>>({});
  const [editing, setEditing] = useState<FieldKey | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<Transaction[]>([]);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const data = bootstrap.data;
  const parsed = useMemo(
    () => (data ? parseQuickEntry(text, vocabularyOf(data)) : null),
    [data, text],
  );

  if (!data || !parsed) {
    return (
      <Modal label="Add a transaction" onClose={onClose} className="palette">
        <Housing label="Quick add" scanlines={false} tilt={false}>
          <p className="muted">Loading…</p>
        </Housing>
      </Modal>
    );
  }

  const amountCents =
    overrides.amount !== undefined ? parseCents(overrides.amount) : parsed.amountCents;
  const date = overrides.date ?? parsed.date;
  const description = overrides.description ?? (parsed.description || parsed.merchant);
  const category = overrides.category ?? parsed.category ?? "";
  const paymentMethod = overrides.payment_method ?? parsed.paymentMethod ?? data.default_payment_method;
  const account = overrides.account ?? parsed.account ?? data.default_account;
  const type = (overrides.transaction_type as TransactionType | undefined) ?? parsed.type;
  const categoryNote = overrides.category
    ? "set by you"
    : parsed.categoryReason || (description ? "server will suggest" : "");
  const ready = amountCents !== null && amountCents > 0 && description.trim().length > 0;
  const missing = !text.trim()
    ? ""
    : amountCents === null || amountCents <= 0
      ? "Add an amount, like 12.50"
      : !description.trim()
        ? "Add what it was for"
        : "";

  function reset() {
    setText("");
    setOverrides({});
    setEditing(null);
    setDuplicate(false);
    setProblem("");
    input.current?.focus();
  }

  async function save(close: boolean) {
    if (!ready || busy || amountCents === null) return;
    setBusy(true);
    setProblem("");
    try {
      const row = await post<Transaction>("/api/transactions", {
        transaction_date: date,
        description: description.trim(),
        amount_cents: amountCents,
        category,
        account,
        payment_method: paymentMethod,
        merchant: parsed?.merchant ?? "",
        transaction_type: type,
        notes: parsed?.notes ?? "",
        category_manual: Boolean(category),
        allow_duplicate: duplicate,
      });
      setSaved((items) => [row, ...items].slice(0, 6));
      await refresh();
      if (close) {
        toast.show(`Saved ${row.description} · ${money(row.amount_cents)}.`);
        onClose();
      } else {
        reset();
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "duplicate") {
        setDuplicate(true);
        setProblem("This looks like one you already saved. Press Enter again to save it anyway.");
      } else {
        setProblem(error instanceof Error ? error.message : "Could not save.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function undo(row: Transaction) {
    try {
      await post("/api/transactions/delete", { ids: [row.id] });
      setSaved((items) => items.filter((item) => item.id !== row.id));
      await refresh();
    } catch (error) {
      toast.error(error);
    }
  }

  function setField(key: FieldKey, value: string) {
    setOverrides((current) => ({ ...current, [key]: value }));
    setDuplicate(false);
  }

  function finishEditing() {
    setEditing(null);
    window.setTimeout(() => input.current?.focus(), 0);
  }

  const budget = overview.data?.budget;
  const meter =
    budget && budget.week.left >= 0
      ? { label: "LEFT THIS WEEK", value: money(budget.week.left) }
      : overview.data
        ? { label: "THIS MONTH", value: money(overview.data.spent) }
        : null;

  const categories = data.categories.map((item) => item.name).filter((name) => name !== "Uncategorized");
  const chipCategories = [
    ...(category ? [category] : []),
    ...categories.filter((name) => name !== category),
  ].slice(0, 9);

  const cells: {
    key: FieldKey;
    label: string;
    shown: string;
    set: boolean;
    note?: string;
  }[] = [
    {
      key: "amount",
      label: "Amount",
      shown: amountCents !== null ? money(amountCents) : "—",
      set: amountCents !== null,
    },
    {
      key: "date",
      label: "Date",
      shown: dayLabel(date, data.today).split(" · ")[0] ?? date,
      set: Boolean(parsed.dateWords || overrides.date),
      note: dayLabel(date, data.today).split(" · ")[1],
    },
    { key: "description", label: "Description", shown: description || "—", set: Boolean(description) },
    { key: "category", label: "Category", shown: category || "Auto", set: Boolean(category), note: categoryNote },
    { key: "payment_method", label: "Paid with", shown: paymentMethod, set: Boolean(parsed.paymentMethod || overrides.payment_method) },
    { key: "account", label: "Account", shown: account, set: Boolean(parsed.account || overrides.account) },
    { key: "transaction_type", label: "Type", shown: type, set: type !== "expense" },
  ];

  function editor(key: FieldKey) {
    const common = {
      autoFocus: true,
      onBlur: finishEditing,
      onKeyDown: (event: React.KeyboardEvent) => {
        if (event.key === "Enter" || event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          finishEditing();
        }
      },
    };
    if (key === "category" || key === "payment_method" || key === "account" || key === "transaction_type") {
      const options =
        key === "category"
          ? categories
          : key === "payment_method"
            ? data?.payment_methods ?? []
            : key === "account"
              ? data?.accounts ?? []
              : TYPES;
      const current = key === "category" ? category : key === "payment_method" ? paymentMethod : key === "account" ? account : type;
      return (
        <select
          {...common}
          aria-label={key}
          value={current}
          onChange={(event) => setField(key, event.target.value)}
        >
          {key === "category" ? <option value="">Suggest on save</option> : null}
          {options.map((option) => (
            <option key={option}>{option}</option>
          ))}
        </select>
      );
    }
    const value =
      key === "amount" ? (overrides.amount ?? (amountCents !== null ? centsToInput(amountCents) : "")) : key === "date" ? date : description;
    return (
      <input
        {...common}
        aria-label={key}
        type={key === "date" ? "date" : "text"}
        inputMode={key === "amount" ? "decimal" : undefined}
        value={value}
        onChange={(event) => setField(key, event.target.value)}
      />
    );
  }

  return (
    <Modal label="Add a transaction" onClose={onClose} className="palette">
      <Housing label="Quick add" tilt={false}>
        <div className="row between">
          <span className="led-label">
            <span className="led-dot" aria-hidden="true" />
            Quick add
          </span>
          {meter ? (
            <span className="row small" style={{ gap: 10 }}>
              <span className="dim tiny caps">{meter.label}</span>
              <span
                className="num"
                style={{
                  color: "var(--accent)",
                  fontFamily: "var(--dots)",
                  fontWeight: 900,
                  fontSize: 22,
                  textShadow: "0 0 10px rgba(212,245,60,.6)",
                }}
              >
                <Odometer text={meter.value} />
              </span>
            </span>
          ) : null}
        </div>
        <div className="palette-input">
          <span className="prompt" aria-hidden="true">
            ›
          </span>
          <input
            ref={input}
            autoFocus
            aria-label="Describe the transaction"
            placeholder="12.50 chipotle lunch yesterday apple pay"
            value={text}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => {
              setText(event.target.value);
              setDuplicate(false);
              setProblem("");
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void save(event.metaKey || event.ctrlKey);
              }
            }}
          />
          <button
            type="button"
            className="btn primary"
            disabled={!ready || busy}
            onClick={() => void save(false)}
          >
            Save <kbd>↵</kbd>
          </button>
        </div>
        <div className="tokens" aria-label="How the line was read">
          {parsed.tokens
            .filter((token) => token.role !== "filler")
            .map((token, index) => {
              const color =
                token.role === "category" ? categoryColor(parsed.category ?? "") : (ROLE_COLORS[token.role] ?? "#E9EDE3");
              return (
                <span
                  key={`${token.text}${index}`}
                  className="token"
                  style={{
                    color,
                    borderColor: rgba(color, token.role === "text" ? 0.15 : 0.45),
                    background: token.role === "text" ? "transparent" : rgba(color, 0.07),
                    textShadow: token.role === "text" ? undefined : `0 0 8px ${rgba(color, 0.5)}`,
                  }}
                >
                  {ROLE_NAMES[token.role] ? <small>{ROLE_NAMES[token.role]}</small> : null}
                  {token.text}
                </span>
              );
            })}
          {parsed.notes ? (
            <span className="token" style={{ color: "#A7AF9E" }}>
              <small>NOTE</small>
              {parsed.notes}
            </span>
          ) : null}
        </div>
        <div className="fields">
          {cells.map((cell) =>
            editing === cell.key ? (
              <div key={cell.key} className={`fieldcell ${cell.key === "description" ? "wide" : ""}`}>
                <span className="label">{cell.label}</span>
                {editor(cell.key)}
              </div>
            ) : (
              <button
                key={cell.key}
                type="button"
                className={`fieldcell ${cell.key === "description" ? "wide" : ""}`}
                onClick={() => setEditing(cell.key)}
                aria-label={`${cell.label}: ${cell.shown}. Change`}
              >
                <span className="label">{cell.label}</span>
                <span
                  className={`v ${cell.set ? "set" : ""} ${cell.shown === "—" || cell.shown === "Auto" ? "blank" : ""}`}
                  style={cell.key === "category" && category ? { color: categoryColor(category) } : undefined}
                >
                  {cell.shown}
                </span>
                {cell.note ? <span className="tiny dim">{cell.note}</span> : null}
              </button>
            ),
          )}
        </div>
        <div className="chips" role="group" aria-label="Category">
          {chipCategories.map((name) => {
            const color = categoryColor(name);
            const on = name === category;
            return (
              <button
                key={name}
                type="button"
                className="chip"
                aria-pressed={on}
                style={on ? { background: color, boxShadow: `0 0 14px ${rgba(color, 0.45)}` } : undefined}
                onClick={() => {
                  setField("category", on ? "" : name);
                  input.current?.focus();
                }}
              >
                <span className="swatch" style={{ background: on ? "#10120e" : color }} />
                {name}
              </button>
            );
          })}
        </div>
        {problem || missing ? (
          <div className={`signal ${duplicate ? "warn" : problem ? "up" : "info"}`} role="alert">
            <span className="mark">{duplicate ? "▲" : "●"}</span>
            <span className="grow">{problem || missing}</span>
            {duplicate ? (
              <button type="button" className="btn small" onClick={() => void save(false)}>
                Save anyway
              </button>
            ) : null}
          </div>
        ) : null}
        <div className="hints">
          <span>
            <kbd>↵</kbd> save &amp; next
          </span>
          <span>
            <kbd>⌘</kbd>
            <kbd>↵</kbd> save &amp; close
          </span>
          <span>
            <kbd>esc</kbd> close
          </span>
          <span>#tag sets category · “yesterday”, “fri”, “3 days ago” · “note: …”</span>
        </div>
        {saved.length ? (
          <div className="stack tight" aria-label="Saved just now">
            <span className="label">Saved just now</span>
            {saved.map((row) => (
              <div key={row.id} className="row small" style={{ gap: 10 }}>
                <span className="led" style={{ width: 7, height: 7, background: "var(--accent)", boxShadow: "0 0 6px var(--accent)" }} />
                <span className="grow">
                  {row.description} <span className="dim">· {row.category} · {dayLabel(row.transaction_date, data.today)}</span>
                </span>
                <span className="num">{money(row.amount_cents)}</span>
                <button type="button" className="btn ghost small" onClick={() => void undo(row)}>
                  Undo
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </Housing>
    </Modal>
  );
}
