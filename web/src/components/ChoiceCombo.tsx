import { useMutation } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { type ChoiceKind, type ChoiceUsage, get, post } from "../api";
import { money, shortDate } from "../lib/format";
import { useChoices, useRefresh } from "../queries";
import { Modal, useToast } from "./feedback";
import { Icon } from "./icons";
import { Glyph } from "./instrument";
import { namesOf, Select } from "./pickers";
import { Popover } from "./popover";

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
}: {
  kind: ChoiceKind;
  value: string;
  onChange: (value: string) => void;
  label: string;
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
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (open) list.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const entries = choices.data?.[kind] ?? [];
  const typed = query.trim();
  const filtered = useMemo(() => {
    const needle = typed.toLowerCase();
    return needle ? entries.filter((entry) => entry.name.toLowerCase().includes(needle)) : entries;
  }, [entries, typed]);
  const exact = entries.some((entry) => entry.name.toLowerCase() === typed.toLowerCase());
  const canCreate = typed.length > 0 && !exact;
  const options = [...filtered.map((entry) => entry.name), ...(canCreate ? [`Add “${typed}”`] : [])];

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
        actions: [
          result.undo
            ? {
                label: "Undo",
                run: async () => {
                  await post(`/api/choices/${kind}/restore`, result.undo);
                  await refresh();
                },
              }
            : null,
        ],
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
        <span>{label}</span>
        <input
          ref={input}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open ? `${id}o${active}` : undefined}
          value={open ? query : value}
          placeholder={open ? value || `Search or add a ${LABELS[kind]}` : `Choose ${LABELS[kind]}`}
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
      <Icon name="down" size={8} className="caret" />
      {open && options.length ? (
        <Popover anchor={input} onClose={() => setOpen(false)} match>
          <ul className="options" role="listbox" id={listId} aria-label={label} ref={list}>
            {options.map((option, index) => {
              const entry = filtered[index];
              return (
                <li
                  key={option}
                  id={`${id}o${index}`}
                  role="option"
                  aria-selected={index === active}
                  className={`option ${index === active ? "active" : ""}`}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    pick(index);
                  }}
                  onMouseMove={() => setActive(index)}
                >
                  {kind === "category" && entry ? <Glyph category={entry.name} small /> : null}
                  {entry ? null : <Icon name="plus" />}
                  <span className="truncate grow">{option}</span>
                  {entry?.count ? <span className="count">{entry.count}</span> : null}
                  {entry && !entry.locked && !entry.default ? (
                    <button
                      type="button"
                      className="remove"
                      tabIndex={-1}
                      aria-label={`Remove ${entry.name}`}
                      title={entry.unused ? "Remove (Shift+Delete)" : "Move its transactions, then remove"}
                      onMouseDown={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        void remove(entry.name);
                      }}
                    >
                      <Icon name="close" size={8} />
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </Popover>
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
        <p className="muted">…</p>
      ) : (
        <>
          <p className="muted">
            {usage.count} transaction{usage.count === 1 ? "" : "s"}
          </p>
          <Select
            label="Move them to"
            value={replacement}
            options={namesOf(usage.replacements, kind === "category")}
            onChange={setReplacement}
          />
          {usage.latest.length ? (
            <div className="table-wrap short">
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
