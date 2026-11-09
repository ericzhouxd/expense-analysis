import { useMutation } from "@tanstack/react-query";
import { useId, useMemo, useRef, useState } from "react";

import { type ChoiceKind, type ChoiceUsage, get, post } from "../api";
import { money, shortDate } from "../lib/format";
import { categoryColor } from "../lib/glyphs";
import { useChoices, useRefresh } from "../queries";
import { Modal, useToast } from "./feedback";

const LABELS: Record<ChoiceKind, string> = {
  category: "category",
  account: "account",
  payment_method: "payment method",
};

/**
 * A searchable choice field. Type to filter or create a new value; × (or
 * Shift+Delete on the highlighted row) removes a choice: unused ones vanish with
 * an Undo, used ones open a dialog that moves their transactions elsewhere.
 */
export function ChoiceCombo({
  kind,
  value,
  onChange,
  label,
  allowCreate = true,
  autoFocus = false,
  compact = false,
}: {
  kind: ChoiceKind;
  value: string;
  onChange: (value: string) => void;
  label?: string;
  allowCreate?: boolean;
  autoFocus?: boolean;
  compact?: boolean;
}) {
  const id = useId();
  const choices = useChoices();
  const refresh = useRefresh();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [removing, setRemoving] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const entries = choices.data?.[kind] ?? [];
  const typed = query.trim();
  const filtered = useMemo(() => {
    const needle = typed.toLowerCase();
    return needle ? entries.filter((entry) => entry.name.toLowerCase().includes(needle)) : entries;
  }, [entries, typed]);
  const exact = entries.some((entry) => entry.name.toLowerCase() === typed.toLowerCase());
  const canCreate = allowCreate && typed.length > 0 && !exact;
  const options = [...filtered.map((entry) => entry.name), ...(canCreate ? [`+ ${typed}`] : [])];

  const create = useMutation({
    mutationFn: (name: string) => post(`/api/choices/${kind}/save`, { name }),
    onSuccess: async (_, name) => {
      await refresh();
      onChange(name);
      toast.show(`Added ${LABELS[kind]} “${name}”.`);
    },
    onError: toast.error,
  });

  async function remove(name: string) {
    const entry = entries.find((item) => item.name === name);
    if (!entry || entry.locked) return;
    if (!entry.unused) {
      setRemoving(name);
      setOpen(false);
      return;
    }
    try {
      const result = await post<{ undo: { name: string; spending_class: string | null } | null }>(
        `/api/choices/${kind}/delete`,
        { source: name },
      );
      if (value === name) onChange("");
      await refresh();
      toast.show(`Removed “${name}”.`, {
        action: result.undo
          ? {
              label: "Undo",
              run: async () => {
                await post(`/api/choices/${kind}/restore`, result.undo);
                await refresh();
              },
            }
          : undefined,
      });
    } catch (error) {
      toast.error(error);
    }
  }

  function pick(index: number) {
    const option = options[index];
    if (option === undefined) return;
    if (canCreate && index === options.length - 1) {
      create.mutate(typed);
    } else {
      onChange(option);
    }
    setQuery("");
    setOpen(false);
  }

  const listId = `${id}list`;
  return (
    <div className="combo">
      <label className="field">
        {label ? <span>{label}</span> : null}
        <input
          ref={input}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open ? `${id}o${active}` : undefined}
          autoFocus={autoFocus}
          value={open ? query : value}
          placeholder={open ? value || `Search or add a ${LABELS[kind]}` : `Choose ${LABELS[kind]}`}
          style={compact ? { minHeight: 32 } : undefined}
          onFocus={() => {
            setOpen(true);
            setQuery("");
            setActive(Math.max(0, entries.findIndex((entry) => entry.name === value)));
          }}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
              setActive((index) => Math.min(options.length - 1, index + 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((index) => Math.max(0, index - 1));
            } else if (event.key === "Enter" && open) {
              event.preventDefault();
              pick(active);
            } else if (event.key === "Escape" && open) {
              event.stopPropagation();
              setOpen(false);
            } else if (event.key === "Delete" && event.shiftKey && open) {
              event.preventDefault();
              const name = filtered[active]?.name;
              if (name) void remove(name);
            }
          }}
        />
      </label>
      {open && options.length ? (
        <ul className="combo-list" role="listbox" id={listId}>
          {options.map((option, index) => {
            const entry = filtered[index];
            return (
              <li
                key={option}
                id={`${id}o${index}`}
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(index);
                }}
                onMouseEnter={() => setActive(index)}
              >
                {kind === "category" && entry ? (
                  <span
                    className="led"
                    style={{ width: 7, height: 7, background: categoryColor(entry.name) }}
                    aria-hidden="true"
                  />
                ) : null}
                <span>{option}</span>
                {entry ? <span className="count">{entry.count || ""}</span> : null}
                {entry && !entry.locked && !entry.default ? (
                  <button
                    type="button"
                    className="remove"
                    aria-label={`Remove ${entry.name}`}
                    title={entry.unused ? "Remove (Shift+Delete)" : "Move its transactions, then remove"}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      void remove(entry.name);
                    }}
                  >
                    ×
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {removing ? (
        <RemoveDialog
          kind={kind}
          name={removing}
          onClose={() => setRemoving(null)}
          onDone={(replacement) => {
            if (value === removing) onChange(replacement);
            setRemoving(null);
          }}
        />
      ) : null}
    </div>
  );
}

/** Removing a used choice: show where it's used and move those rows to another value. */
export function RemoveDialog({
  kind,
  name,
  onClose,
  onDone,
}: {
  kind: ChoiceKind;
  name: string;
  onClose: () => void;
  onDone: (replacement: string) => void;
}) {
  const refresh = useRefresh();
  const toast = useToast();
  const [usage, setUsage] = useState<ChoiceUsage | null>(null);
  const [replacement, setReplacement] = useState("");
  const [busy, setBusy] = useState(false);
  const loaded = useRef(false);
  if (!loaded.current) {
    loaded.current = true;
    get<ChoiceUsage>(`/api/choices/${kind}/usage?name=${encodeURIComponent(name)}`)
      .then((data) => {
        setUsage(data);
        setReplacement(data.replacements[0] ?? "");
      })
      .catch(toast.error);
  }

  async function confirm() {
    setBusy(true);
    try {
      await post(`/api/choices/${kind}/delete`, { source: name, replacement });
      await refresh();
      toast.show(`Moved ${usage?.count ?? 0} to “${replacement}” and removed “${name}”.`);
      onDone(replacement);
    } catch (error) {
      toast.error(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal label={`Remove ${name}`} onClose={onClose}>
      <h2>Remove “{name}”</h2>
      {usage === null ? (
        <p className="muted">Checking where it's used…</p>
      ) : (
        <>
          <p className="muted" style={{ margin: 0 }}>
            {usage.count} transaction{usage.count === 1 ? " uses" : "s use"} this {LABELS[kind]}. Choose where
            they should go instead.
          </p>
          <label className="field">
            <span>Move them to</span>
            <select value={replacement} onChange={(event) => setReplacement(event.target.value)}>
              {usage.replacements.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          </label>
          {usage.latest.length ? (
            <div className="table-wrap" style={{ maxHeight: 240, overflowY: "auto" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Description</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {usage.latest.map((row) => (
                    <tr key={row.id}>
                      <td className="dim">{shortDate(row.transaction_date)}</td>
                      <td>{row.description}</td>
                      <td className="num">{money(row.amount_cents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
      <div className="row end">
        <button type="button" className="btn ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn danger"
          disabled={!usage || !replacement || busy}
          onClick={confirm}
        >
          Move and remove
        </button>
      </div>
    </Modal>
  );
}
