import { type KeyboardEvent, type ReactNode, useMemo, useRef, useState } from "react";

import { ApiError, type FrequentEntry, post, type Suggestion, type Transaction } from "../api";
import { centsToInput, money, parseCents, shortDate } from "../lib/format";
import { categoryColor, LED, rgba } from "../lib/glyphs";
import { matchingEntries, wordsMatch } from "../lib/palette";
import { parseQuickEntry, type Role, type TransactionType } from "../lib/quickParse";
import { useBootstrap, useOverview, useRefresh, useSuggestion, vocabularyOf } from "../queries";
import { BUDGET_TABS, navigate, ROUTES, SETTINGS_TABS, transactionsUrl } from "../router";
import { Modal, useToast } from "./feedback";
import { Icon, type IconName } from "./icons";
import { Glyph, Housing, Led, Odometer, Pips } from "./instrument";
import { DatePicker, namesOf, Select, typeOptions } from "./pickers";
import { Info, Notice } from "./ui";

type FieldKey = "amount" | "date" | "description" | "category" | "payment_method" | "account" | "transaction_type";

const PAGES = [
  ...ROUTES.map((route) => ({ to: route.path as string, label: route.label as string, icon: route.icon as IconName })),
  ...BUDGET_TABS.slice(1).map((tab) => ({ to: tab.to, label: `Budget: ${tab.label}`, icon: "budget" as IconName })),
  ...SETTINGS_TABS.slice(1).map((tab) => ({ to: tab.to, label: `Settings: ${tab.label}`, icon: "settings" as IconName })),
];

interface Offer {
  key: string;
  icon: ReactNode;
  title: string;
  meta?: string;
  aside?: string;
  run: () => void;
}

/** Each part of the line in the color of what it was read as. */
const ROLE: Partial<Record<Role, { name: string; color: string }>> = {
  amount: { name: "AMT", color: LED.accent },
  date: { name: "DATE", color: LED.blue },
  type: { name: "TYPE", color: LED.amber },
  payment: { name: "PAY", color: LED.violet },
  account: { name: "ACCT", color: LED.sage },
};

/** A page, in a tile like the category glyphs. */
function IconTile({ name }: { name: IconName }) {
  return (
    <span className="glyph-tile icon-tile" aria-hidden="true">
      <Icon name={name} size={16} />
    </span>
  );
}

const WHY: Partial<Record<Suggestion["source"], { label: string; color: string }>> = {
  rule: { label: "Your rule", color: LED.blue },
  name: { label: "Same name", color: LED.accent },
  words: { label: "Same words", color: LED.accent },
  merchant: { label: "Same merchant", color: LED.accent },
  "built-in": { label: "Built-in word", color: LED.amber },
};

/** A lamp for where a suggested category came from; pressing it shows the evidence. */
function Why({ suggestion }: { suggestion: Suggestion }) {
  const why = WHY[suggestion.source];
  if (!why) return null;
  const agree = Math.round(suggestion.share * 10);
  return (
    <Info label="Category" lamp={<Led color={why.color} lit />}>
      <span className="why">
        <span className="label">{why.label}</span>
        {suggestion.evidence.map((item) => (
          <span key={`${item.text} ${item.category}`} className="why-row">
            <span className="truncate">{item.text}</span>
            <Icon name="arrow" />
            <span className="truncate" style={{ color: categoryColor(item.category) }}>
              {item.category}
            </span>
            <span className="dim">{item.count ? `${item.count}×` : ""}</span>
          </span>
        ))}
        {suggestion.source === "rule" || suggestion.source === "built-in" ? null : (
          <Pips
            label={`${Math.round(suggestion.share * 100)}% of the evidence agrees`}
            pips={Array.from({ length: 10 }, (_, index) => (index < agree ? "ok" : "off"))}
          />
        )}
      </span>
    </Info>
  );
}

/**
 * The ⌘K panel. A line with an amount becomes a draft, read live and correctable
 * in place; Enter adds it and the panel stays open for the next one. A line
 * without an amount finds things: purchases to log again, transactions, pages.
 */
export function QuickAdd({ onClose, initialText = "" }: { onClose: () => void; initialText?: string }) {
  const bootstrap = useBootstrap();
  const overview = useOverview(null, "everyday");
  const refresh = useRefresh();
  const toast = useToast();
  const [text, setText] = useState(initialText);
  const [overrides, setOverrides] = useState<Partial<Record<FieldKey, string>>>({});
  /** The earlier purchase this draft repeats; what is typed still wins over it. */
  const [chosenLike, setLike] = useState<FrequentEntry | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<Transaction[]>([]);
  const [problem, setProblem] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const data = bootstrap.data;
  const like = chosenLike && text.includes(chosenLike.description) ? chosenLike : null;
  // A repeated description is taken whole: its "card" or "7" is not a payment method or an amount.
  const line = like ? text.replace(like.description, " ") : text;
  const parsed = useMemo(() => (data ? parseQuickEntry(line, vocabularyOf(data)) : null), [data, line]);

  // A word like "refund" says the type; a repeated purchase is a purchase.
  const typed = like || parsed?.tokens.some((token) => token.role === "type");
  const type =
    (overrides.transaction_type as TransactionType | undefined) ??
    (typed ? parsed?.type : data?.defaults.transaction_type) ??
    "expense";
  const description =
    overrides.description ??
    (like
      ? [like.description, parsed?.description].filter(Boolean).join(" ")
      : parsed?.description || parsed?.merchant || "");
  const merchant = parsed?.merchant || like?.merchant || "";
  const suggested = useSuggestion(description, merchant, type).data;

  if (!data || !parsed) {
    return (
      <Modal label="Add or find" onClose={onClose} className="palette">
        <Housing label="Add or find">
          <span className="led-label">
            <span className="led-dot pulse" aria-hidden="true" />
            Warming up
          </span>
        </Housing>
      </Modal>
    );
  }

  const amountCents = overrides.amount !== undefined ? parseCents(overrides.amount) : parsed.amountCents;
  const drafting = parsed.amountCents !== null || overrides.amount !== undefined;
  const date = overrides.date ?? parsed.date;
  // Chosen for this entry, carried over from the one it repeats, or left to the server.
  const picked = overrides.category || parsed.category || "";
  const set = picked || like?.category || "";
  const guess = !set && description.trim() && suggested?.source !== "none" ? suggested : undefined;
  const category = set || guess?.category || "";
  const paymentMethod =
    overrides.payment_method ?? parsed.paymentMethod ?? like?.payment_method ?? data.defaults.payment_method;
  const account = overrides.account ?? parsed.account ?? like?.account ?? data.defaults.account;
  const ready = amountCents !== null && amountCents > 0 && description.trim().length > 0;
  function reset() {
    setText("");
    setOverrides({});
    setLike(null);
    setActive(null);
    setDuplicate(false);
    setProblem("");
    input.current?.focus();
  }

  /** Put an earlier purchase on the line, keeping an amount, date or note already typed. */
  function repeat(entry: FrequentEntry, cents: number | null) {
    setLike(entry);
    const kept = (parsed?.tokens ?? []).filter((token) => token.role !== "text" && token.role !== "filler");
    const note = parsed?.notes ? `note: ${parsed.notes}` : "";
    setText(
      (cents === null
        ? [centsToInput(entry.amount_cents), entry.description]
        : [...kept.map((token) => token.text), entry.description, note]
      )
        .filter(Boolean)
        .join(" "),
    );
    setOverrides(({ description: _, ...rest }) => rest);
    setActive(null);
    setProblem("");
    input.current?.focus();
  }

  function go(to: string) {
    onClose();
    navigate(to);
  }

  const query = text.trim();
  const entryOffer = (entry: FrequentEntry, cents: number | null): Offer => ({
    key: `entry ${entry.description}`,
    icon: <Glyph category={entry.category} />,
    title: entry.description,
    meta: [entry.merchant, entry.category].filter(Boolean).join(" · "),
    aside: cents === null ? money(entry.amount_cents) : "",
    run: () => repeat(entry, cents),
  });
  const pages: Offer[] = PAGES.filter((page) => query && wordsMatch(query, page.label)).map((page) => ({
    key: page.to,
    icon: <IconTile name={page.icon} />,
    title: page.label,
    aside: "Go to",
    run: () => go(page.to),
  }));
  /** Typing the start of a page's name most likely means the page. */
  const named = (title: string) => title.toLowerCase().startsWith(query.toLowerCase());
  const offers: Offer[] = drafting
    ? like || !parsed.description
      ? []
      : matchingEntries(parsed.description, data.frequent, 3)
          .filter((entry) => entry.description.toLowerCase() !== description.toLowerCase())
          .map((entry) => entryOffer(entry, amountCents))
    : [
        ...pages.filter((page) => named(page.title)),
        ...matchingEntries(query, data.frequent, query ? 4 : 5).map((entry) => entryOffer(entry, null)),
        ...(query
          ? [
              {
                key: "search",
                icon: <IconTile name="search" />,
                title: `Search transactions for “${query}”`,
                run: () => go(transactionsUrl({ q: query })),
              },
            ]
          : []),
        ...pages.filter((page) => !named(page.title)),
      ];
  // Enter adds a draft, so nothing under one is chosen until an arrow key says so.
  const chosen = active ?? (drafting || !query ? null : 0);
  const heading = drafting ? "Same as before" : query ? null : "Log again";

  async function save(close: boolean) {
    if (!ready || busy || amountCents === null) return;
    setBusy(true);
    setProblem("");
    try {
      const row = await post<Transaction>("/api/transactions", {
        transaction_date: date,
        description: description.trim(),
        amount_cents: amountCents,
        category: set,
        account,
        payment_method: paymentMethod,
        merchant,
        transaction_type: type,
        notes: parsed?.notes ?? "",
        category_manual: Boolean(set),
        category_chosen: Boolean(picked),
        allow_duplicate: duplicate,
      });
      setSaved((items) => [row, ...items].slice(0, 5));
      await refresh();
      if (close) {
        toast.show(`Added ${row.description}, ${money(row.amount_cents)}.`);
        onClose();
      } else {
        reset();
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "duplicate") {
        setDuplicate(true);
        setProblem("This looks like one you already saved. Press Enter again to add it anyway.");
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
    setProblem("");
  }

  function onKey(event: KeyboardEvent) {
    if (event.key === "Enter") {
      event.preventDefault();
      if (chosen !== null && offers[chosen]) offers[chosen].run();
      else if (drafting) {
        if (ready) void save(event.metaKey || event.ctrlKey);
        else setProblem(amountCents === null || amountCents <= 0 ? "Add an amount, like 12.50." : "Add what it was for.");
      }
    } else if (event.key === "ArrowDown" && offers.length) {
      event.preventDefault();
      setActive(chosen === null ? 0 : Math.min(offers.length - 1, chosen + 1));
    } else if (event.key === "ArrowUp" && offers.length) {
      event.preventDefault();
      setActive(chosen === null || chosen === 0 ? null : chosen - 1);
    }
  }

  const categories = data.categories.map((item) => item.name).filter((name) => name !== "Uncategorized");
  const week = overview.data?.budget?.week;
  const over = week !== undefined && week.left < 0;
  const tokens = parsed.tokens.filter((token) => token.role !== "filler");

  return (
    <Modal label="Add or find" onClose={onClose} className="palette">
      <Housing label="Add or find">
        <div className="row between">
          <span className="led-label">
            <span className="led-dot pulse" aria-hidden="true" />
            {drafting ? "Quick add" : "Add or find"}
          </span>
          {week ? (
            <span className={`palette-left ${over ? "over" : ""}`}>
              <span className="label">{over ? "Over this week" : "Left this week"}</span>
              <Odometer text={money(Math.abs(week.left))} />
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
            role="combobox"
            aria-label="Add a transaction or find something"
            aria-expanded={offers.length > 0}
            aria-controls="palette-offers"
            aria-activedescendant={chosen !== null ? `offer${chosen}` : undefined}
            placeholder="12.50 chipotle lunch yesterday"
            value={text}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => {
              setText(event.target.value);
              setActive(null);
              setDuplicate(false);
              setProblem("");
              if (!event.target.value.trim()) {
                setLike(null);
                setOverrides({});
              }
            }}
            onKeyDown={onKey}
          />
          <button type="button" className="btn primary" disabled={!ready || busy} onClick={() => void save(false)}>
            Add <kbd>↵</kbd>
          </button>
        </div>

        {drafting && tokens.length ? (
          <div className="tokens" aria-hidden="true">
            {tokens.map((token, index) => {
              const role = ROLE[token.role];
              const color = token.role === "category" ? categoryColor(parsed.category ?? "") : role?.color;
              return (
                <span
                  key={`${token.text}${index}`}
                  className="token"
                  style={
                    color
                      ? {
                          color,
                          borderColor: rgba(color, 0.45),
                          background: rgba(color, 0.07),
                          textShadow: `0 0 8px ${rgba(color, 0.5)}`,
                        }
                      : undefined
                  }
                >
                  {color ? <small>{role?.name ?? "CAT"}</small> : null}
                  {token.text}
                </span>
              );
            })}
            {parsed.notes ? (
              <span className="token">
                <small>NOTE</small>
                {parsed.notes}
              </span>
            ) : null}
          </div>
        ) : null}

        {drafting ? (
          <div
            className="fields"
            onKeyDown={(event) => {
              if (event.key === "Enter" && event.target instanceof HTMLInputElement) {
                event.preventDefault();
                void save(event.metaKey || event.ctrlKey);
              }
            }}
          >
            <label className="fieldcell">
              <span className="label">Amount</span>
              <input
                className={`v ${amountCents ? "set" : ""}`}
                inputMode="decimal"
                placeholder="0.00"
                value={overrides.amount ?? (amountCents !== null ? centsToInput(amountCents) : "")}
                aria-invalid={amountCents === null || amountCents <= 0}
                onChange={(event) => setField("amount", event.target.value)}
              />
            </label>
            <label className="fieldcell wide">
              <span className="label">Description</span>
              <input
                className="v"
                placeholder="What was it for?"
                value={description}
                onChange={(event) => setField("description", event.target.value)}
              />
            </label>
            <DatePicker
              look="cell"
              label="Date"
              value={date}
              lit={Boolean(parsed.dateWords || overrides.date)}
              onChange={(value) => setField("date", value)}
            />
            <div className="cell-why">
              <Select
                look="cell"
                label="Category"
                placeholder="Uncategorized"
                value={category}
                options={[{ value: "", label: "Automatic" }, ...namesOf(categories, true)].filter(
                  (option) => option.value || overrides.category,
                )}
                onChange={(value) => setField("category", value)}
              />
              {guess && guess.source !== "default" ? <Why suggestion={guess} /> : null}
            </div>
            <Select
              look="cell"
              label="Paid with"
              className={parsed.paymentMethod || overrides.payment_method || like ? "set" : ""}
              value={paymentMethod}
              options={namesOf(data.payment_methods)}
              onChange={(value) => setField("payment_method", value)}
            />
            <Select
              look="cell"
              label="Account"
              className={parsed.account || overrides.account || like ? "set" : ""}
              value={account}
              options={namesOf(data.accounts)}
              onChange={(value) => setField("account", value)}
            />
            <Select
              look="cell"
              label="Type"
              className={type !== data.defaults.transaction_type ? "set" : ""}
              value={type}
              options={typeOptions(data.transaction_types)}
              onChange={(value) => setField("transaction_type", value)}
            />
          </div>
        ) : null}

        {problem ? (
          <Notice
            tone={duplicate ? "warn" : "up"}
            role="alert"
            action={
              duplicate ? (
                <button type="button" className="btn small" onClick={() => void save(false)}>
                  Add anyway
                </button>
              ) : null
            }
          >
            {problem}
          </Notice>
        ) : null}

        {offers.length ? (
          <div className="offers">
            {heading ? <span className="label">{heading}</span> : null}
            <ul id="palette-offers" className="options" role="listbox" aria-label={heading ?? "Results"}>
              {offers.map((offer, index) => (
                <li
                  key={offer.key}
                  id={`offer${index}`}
                  role="option"
                  aria-selected={index === chosen}
                  className={`option ${index === chosen ? "active" : ""}`}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={offer.run}
                >
                  {offer.icon}
                  <span className="truncate grow">
                    {offer.title}
                    {offer.meta ? <span className="dim small"> {offer.meta}</span> : null}
                  </span>
                  {offer.aside ? <span className="dim nowrap small">{offer.aside}</span> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {saved.length ? (
          <div className="offers" aria-label="Added just now">
            <span className="label">Added just now</span>
            {saved.map((row) => (
              <div key={row.id} className="saved-row">
                <Led color={LED.accent} lit />
                <span className="truncate grow">
                  {row.description}{" "}
                  <span className="dim small">
                    <span style={{ color: categoryColor(row.category) }}>{row.category}</span> · {shortDate(row.transaction_date)}
                  </span>
                </span>
                <span className="num">{money(row.amount_cents)}</span>
                <button type="button" className="btn ghost small" onClick={() => void undo(row)}>
                  Undo
                </button>
              </div>
            ))}
          </div>
        ) : null}

        <div className="hints">
          {drafting ? (
            <>
              <span>
                <kbd>↵</kbd> add, and next
              </span>
              <span>
                <kbd>⌘</kbd> <kbd>↵</kbd> add and close
              </span>
            </>
          ) : (
            <>
              <span>
                <kbd>↑</kbd> <kbd>↓</kbd> choose
              </span>
              <span>
                <kbd>esc</kbd> close
              </span>
            </>
          )}
        </div>
      </Housing>
    </Modal>
  );
}
