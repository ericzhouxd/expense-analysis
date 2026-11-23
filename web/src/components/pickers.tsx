import { type KeyboardEvent, type ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";

import { addDays, dayLabel, iso, monthLabel, parseIso } from "../lib/format";
import { categoryColor } from "../lib/glyphs";
import { readDate } from "../lib/quickParse";
import { useBootstrap } from "../queries";
import { Icon } from "./icons";
import { Glyph } from "./instrument";
import { Popover } from "./popover";

export interface Option {
  value: string;
  label: string;
  /** A heading the option sits under. */
  group?: string;
  /** Draws this category's glyph, in its color. */
  category?: string;
}

export function typeOptions(types: string[]) {
  return types.map((value) => ({ value, label: `${value[0]?.toUpperCase()}${value.slice(1)}` }));
}

/** Names as options; with `glyphs`, each is a category. */
export function namesOf(names: readonly string[], glyphs = false): Option[] {
  return names.map((name) => ({ value: name, label: name, category: glyphs ? name : undefined }));
}

/** field: an inset box. small: the same, shorter. text: reads as text until pointed at. cell: a ⌘K field. */
type Look = "field" | "small" | "text" | "cell";

interface ListProps {
  options: readonly Option[];
  selected: readonly string[];
  onPick: (value: string) => void;
  /** Stays open so several can be picked. */
  many?: boolean;
  /** Shown on the button. */
  children: ReactNode;
  /** A caption above the box. */
  label?: string;
  "aria-label"?: string;
  look?: Look;
  className?: string;
  disabled?: boolean;
  tabIndex?: number;
  title?: string;
}

function ListPicker({
  options,
  selected,
  onPick,
  many = false,
  children,
  label,
  "aria-label": ariaLabel,
  look = "field",
  className = "",
  disabled,
  tabIndex,
  title,
}: ListProps) {
  const id = useId();
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const typed = useRef({ text: "", at: 0 });

  function show() {
    setActive(Math.max(0, options.findIndex((option) => selected.includes(option.value))));
    setOpen(true);
  }

  function pick(index: number) {
    const option = options[index];
    if (!option) return;
    if (!many) setOpen(false);
    onPick(option.value);
  }

  useEffect(() => {
    if (open) list.current?.querySelector(`[data-at="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  function seek(character: string) {
    const now = Date.now();
    const text = (now - typed.current.at < 800 ? typed.current.text : "") + character.toLowerCase();
    typed.current = { text, at: now };
    const hit = options.findIndex((option) => option.label.toLowerCase().startsWith(text));
    if (hit >= 0) setActive(hit);
  }

  function onKey(event: KeyboardEvent) {
    const { key } = event;
    if (!open) {
      if (key === "ArrowDown" || key === "ArrowUp") {
        event.preventDefault();
        event.stopPropagation();
        show();
      }
      return;
    }
    if (key === "Tab") {
      setOpen(false);
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    event.stopPropagation();
    const last = options.length - 1;
    if (key === "Escape") setOpen(false);
    else if (key === "ArrowDown") setActive((index) => Math.min(last, index + 1));
    else if (key === "ArrowUp") setActive((index) => Math.max(0, index - 1));
    else if (key === "Home" || key === "PageUp") setActive(0);
    else if (key === "End" || key === "PageDown") setActive(last);
    else if (key === "Enter" || (key === " " && !typed.current.text.trim())) pick(active);
    else if (key === " " && Date.now() - typed.current.at >= 800) pick(active);
    else if (key.length === 1) seek(key);
    else return;
    event.preventDefault();
  }

  const trigger = (
    <button
      ref={button}
      type="button"
      role="combobox"
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-controls={open ? `${id}list` : undefined}
      aria-activedescendant={open ? `${id}o${active}` : undefined}
      aria-label={ariaLabel ?? label}
      className={`picker picker-${look} ${className}`}
      disabled={disabled}
      tabIndex={tabIndex}
      title={title}
      onClick={(event) => {
        event.stopPropagation();
        if (open) setOpen(false);
        else show();
      }}
      onKeyDown={onKey}
    >
      {look === "cell" && label ? <span className="label">{label}</span> : null}
      <span className="picker-value">{children}</span>
      <Icon name="down" size={8} className="caret" />
    </button>
  );

  return (
    <>
      {label && look !== "cell" ? (
        <div className="field">
          <span>{label}</span>
          {trigger}
        </div>
      ) : (
        trigger
      )}
      {open ? (
        <Popover anchor={button} onClose={() => setOpen(false)} match={look !== "text"}>
          <ul ref={list} className="options" role="listbox" id={`${id}list`} aria-multiselectable={many || undefined} aria-label={ariaLabel ?? label}>
            {options.map((option, index) => (
              <li key={option.value} role="presentation">
                {option.group && option.group !== options[index - 1]?.group ? (
                  <span className="options-group">{option.group}</span>
                ) : null}
                <div
                  id={`${id}o${index}`}
                  data-at={index}
                  role="option"
                  aria-selected={selected.includes(option.value)}
                  className={`option ${index === active ? "active" : ""}`}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseMove={() => setActive(index)}
                  onClick={() => pick(index)}
                >
                  {option.category ? <Glyph category={option.category} small /> : null}
                  <span className="truncate">{option.label}</span>
                  {selected.includes(option.value) ? <Icon name="check" className="chosen" /> : null}
                </div>
              </li>
            ))}
          </ul>
        </Popover>
      ) : null}
    </>
  );
}

type Shared = Omit<ListProps, "selected" | "onPick" | "many" | "children">;

/** Choose one. */
export function Select({
  value,
  onChange,
  placeholder = "Choose",
  ...props
}: Shared & { value: string; onChange: (value: string) => void; placeholder?: string }) {
  const chosen = props.options.find((option) => option.value === value);
  const color = chosen?.category && props.look !== "field" ? categoryColor(chosen.category) : undefined;
  return (
    <ListPicker {...props} selected={[value]} onPick={onChange}>
      {chosen ? <span style={color ? { color } : undefined}>{chosen.label}</span> : <span className="faint">{placeholder}</span>}
    </ListPicker>
  );
}

/** Choose any number. */
export function MultiSelect({
  values,
  onChange,
  placeholder = "Choose",
  ...props
}: Shared & { values: string[]; onChange: (values: string[]) => void; placeholder?: string }) {
  return (
    <ListPicker
      {...props}
      many
      selected={values}
      onPick={(value) => onChange(values.includes(value) ? values.filter((item) => item !== value) : [...values, value])}
    >
      {values.length ? values.join(", ") : <span className="faint">{placeholder}</span>}
    </ListPicker>
  );
}

const WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** A month of LED cells; the chosen day is lit. */
function Calendar({
  value,
  today,
  onPick,
  onClose,
  focused,
}: {
  value: string;
  today: string;
  onPick: (date: string) => void;
  onClose: () => void;
  /** Opened from the keyboard, so it takes the focus. */
  focused: boolean;
}) {
  const [cursor, setCursor] = useState(value || today);
  const grid = useRef<HTMLDivElement>(null);
  const keyed = useRef(focused);
  const date = parseIso(cursor);
  const first = new Date(date.getFullYear(), date.getMonth(), 1);
  const start = addDays(first, -((first.getDay() + 6) % 7));
  const days = Array.from({ length: 42 }, (_, index) => addDays(start, index));

  useEffect(() => {
    if (keyed.current) grid.current?.querySelector<HTMLElement>("[tabindex='0']")?.focus();
  }, [cursor]);

  function months(step: number) {
    const last = new Date(date.getFullYear(), date.getMonth() + step + 1, 0).getDate();
    setCursor(iso(new Date(date.getFullYear(), date.getMonth() + step, Math.min(date.getDate(), last))));
  }

  function onKey(event: KeyboardEvent) {
    event.stopPropagation();
    const steps: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    const step = steps[event.key];
    const monday = (date.getDay() + 6) % 7;
    if (event.key === "Escape" || event.key === "Tab") onClose();
    else if (event.target instanceof HTMLElement && !event.target.closest(".days")) return;
    else if (step) setCursor(iso(addDays(date, step)));
    else if (event.key === "Home") setCursor(iso(addDays(date, -monday)));
    else if (event.key === "End") setCursor(iso(addDays(date, 6 - monday)));
    else if (event.key === "PageUp") months(-1);
    else if (event.key === "PageDown") months(1);
    else if (event.key === "Enter" || event.key === " ") onPick(cursor);
    else return;
    keyed.current = true;
    event.preventDefault();
  }

  const month = cursor.slice(0, 7);
  const keep = (event: { preventDefault: () => void }) => event.preventDefault();
  return (
    <div className="datepick" role="dialog" aria-label="Choose a date" onKeyDown={onKey}>
      <div className="datepick-head">
        <button type="button" className="step" tabIndex={-1} aria-label="Previous month" onMouseDown={keep} onClick={() => months(-1)}>
          <Icon name="left" />
        </button>
        <span aria-live="polite">{monthLabel(month)}</span>
        <button type="button" className="step" tabIndex={-1} aria-label="Next month" onMouseDown={keep} onClick={() => months(1)}>
          <Icon name="right" />
        </button>
      </div>
      <div className="days-head" aria-hidden="true">
        {WEEK.map((name) => (
          <span key={name}>{name.slice(0, 2)}</span>
        ))}
      </div>
      <div className="days" ref={grid} role="group" aria-label={monthLabel(month)}>
        {days.map((day) => {
          const key = iso(day);
          return (
            <button
              key={key}
              type="button"
              tabIndex={key === cursor ? 0 : -1}
              className={`day-cell ${key.startsWith(month) ? "" : "outside"} ${key === today ? "today" : ""} ${key === value ? "on" : ""}`}
              aria-label={`${dayLabel(key)}, ${day.getFullYear()}`}
              aria-pressed={key === value}
              onMouseDown={keep}
              onClick={() => onPick(key)}
            >
              {day.getDate()}
            </button>
          );
        })}
      </div>
      <div className="datepick-foot">
        {[
          ["Today", today],
          ["Yesterday", iso(addDays(parseIso(today), -1))],
        ].map(([name = "", day = today]) => (
          <button key={name} type="button" className="btn ghost small" tabIndex={-1} onMouseDown={keep} onClick={() => onPick(day)}>
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Read a typed date the way ⌘K does: "fri", "nov 3", "3 days ago", 2026-11-03. */
function typedDate(text: string, today: string): string | null {
  const words = text.trim().toLowerCase().split(/\s+/);
  const hit = readDate(words, 0, parseIso(today));
  return hit && hit.used === words.length ? iso(hit.date) : null;
}

/** A date to type or pick from a calendar. */
export function DatePicker({
  value,
  onChange,
  label,
  "aria-label": ariaLabel,
  look = "field",
  placeholder = "Pick a date",
  lit = false,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  "aria-label"?: string;
  look?: "field" | "cell";
  placeholder?: string;
  /** Read from the line, in a ⌘K field. */
  lit?: boolean;
  className?: string;
}) {
  const bootstrap = useBootstrap();
  const today = bootstrap.data?.today ?? iso(new Date());
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState<"pointer" | "keys" | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const shown = useMemo(() => (value ? dayLabel(value, today).split(" · ").pop() ?? value : ""), [value, today]);
  const touch = typeof window !== "undefined" && window.matchMedia("(pointer: coarse)").matches;

  function commit() {
    if (draft === null) return;
    const read = draft.trim() ? typedDate(draft, today) : null;
    if (read && read !== value) onChange(read);
    setDraft(null);
  }

  function close() {
    setOpen(null);
    if (document.activeElement !== input.current) input.current?.focus();
  }

  const body = (
    <div ref={look === "cell" ? undefined : box} className={look === "cell" ? "" : "date-field"}>
      <input
        ref={input}
        role="combobox"
        aria-haspopup="dialog"
        aria-expanded={open !== null}
        aria-label={ariaLabel ?? label}
        inputMode={touch ? "none" : undefined}
        className={look === "cell" ? `v ${lit ? "set" : ""}` : "input"}
        placeholder={placeholder}
        value={draft ?? shown}
        aria-invalid={draft !== null && Boolean(draft.trim()) && typedDate(draft, today) === null}
        autoComplete="off"
        spellCheck={false}
        onClick={() => setOpen("pointer")}
        onFocus={(event) => event.target.select()}
        onBlur={() => {
          commit();
        }}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            event.stopPropagation();
            commit();
            setOpen("keys");
          } else if (event.key === "Enter" && draft !== null) {
            event.preventDefault();
            event.stopPropagation();
            commit();
            setOpen(null);
          } else if (event.key === "Escape" && (open || draft !== null)) {
            event.preventDefault();
            event.stopPropagation();
            setDraft(null);
            setOpen(null);
          } else if (event.key === "Tab") {
            setOpen(null);
          }
        }}
      />
      {look === "field" ? <Icon name="calendar" /> : null}
      {open ? (
        <Popover anchor={box} onClose={() => setOpen(null)}>
          <Calendar
            key={open}
            value={value}
            today={today}
            focused={open === "keys"}
            onClose={close}
            onPick={(date) => {
              setDraft(null);
              onChange(date);
              close();
            }}
          />
        </Popover>
      ) : null}
    </div>
  );

  if (look === "cell") {
    return (
      <div ref={box} className={`fieldcell ${className}`} onClick={() => input.current?.focus()}>
        <span className="label">{label}</span>
        {body}
      </div>
    );
  }
  return label ? (
    <div className={`field ${className}`}>
      <span>{label}</span>
      {body}
    </div>
  ) : (
    body
  );
}
