import {
  type CSSProperties,
  type ReactNode,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { money, versus } from "../lib/format";
import { categoryColor, glyphShadow, hot, rgba } from "../lib/glyphs";

const MOTION_QUERY = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    (callback) => {
      const query = window.matchMedia(MOTION_QUERY);
      query.addEventListener("change", callback);
      return () => query.removeEventListener("change", callback);
    },
    () => window.matchMedia(MOTION_QUERY).matches,
    () => false,
  );
}

/** The glass-covered LED panel. */
export function Housing({
  children,
  label,
  className = "",
  scanlines = true,
}: {
  children: ReactNode;
  label: string;
  className?: string;
  scanlines?: boolean;
}) {
  return (
    <div className={`housing ${className}`}>
      <span className="screw tl" aria-hidden="true" />
      <span className="screw tr" aria-hidden="true" />
      <span className="screw bl" aria-hidden="true" />
      <span className="screw br" aria-hidden="true" />
      <section className="screen" aria-label={label}>
        {scanlines ? <div className="scan" aria-hidden="true" /> : null}
        {children}
      </section>
    </div>
  );
}

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

/**
 * Dot-matrix fonts draw "." as a plus-shaped cluster at display sizes, which
 * reads like "+". Draw decimal points and thousands commas as square LED pixels.
 */
function Point({ comma = false }: { comma?: boolean }) {
  return (
    <span className={`odo-static odo-point ${comma ? "comma" : ""}`} aria-hidden="true">
      <i />
    </span>
  );
}

/** The unlit segments behind a lit number: every digit shows as 8. */
function Ghost({ text }: { text: string }) {
  return (
    <>
      {[...text].map((character, index) =>
        character === "." || character === "," ? (
          <Point key={index} comma={character === ","} />
        ) : (
          <span key={index}>{/\d/.test(character) ? "8" : character}</span>
        ),
      )}
    </>
  );
}

/** Digits roll like an odometer when the value changes; other characters stay put. */
export function Odometer({ text }: { text: string }) {
  const characters = [...text];
  return (
    <span className="odo" role="text" aria-label={text}>
      {characters.map((character, index) => {
        const fromRight = characters.length - index;
        if (character === "." || character === ",") {
          return <Point key={`p${fromRight}`} comma={character === ","} />;
        }
        if (!/\d/.test(character)) {
          return (
            <span key={`s${fromRight}`} className="odo-static" aria-hidden="true">
              {character}
            </span>
          );
        }
        return (
          <span key={`d${fromRight}`} className="odo-col" aria-hidden="true">
            <span
              className="odo-strip"
              style={{
                transform: `translateY(${-Number(character) * 1.6}em)`,
                transitionDelay: `${(fromRight - 1) * 70}ms`,
              }}
            >
              {DIGITS.map((digit) => (
                <span key={digit}>{digit}</span>
              ))}
            </span>
          </span>
        );
      })}
    </span>
  );
}

/** The featured LED number: hot core, layered glow, bloom, lens streak and unlit ghost. */
export function HeroNumber({
  value,
  ghost,
  tone = "accent",
}: {
  value: string;
  ghost?: string;
  tone?: "accent" | "over" | "amber" | "plain";
}) {
  return (
    <div className={`hero boot ${tone === "accent" ? "" : tone}`}>
      <div className="hero-bloom" aria-hidden="true" />
      <span className="hero-ghost" aria-hidden="true">
        <Ghost text={ghost ?? value} />
      </span>
      <span className="hero-value">
        <Odometer text={value} />
      </span>
      <div className="hero-streak" aria-hidden="true" />
      <div className="hero-streak wide" aria-hidden="true" />
    </div>
  );
}

export function Readouts({ children }: { children: ReactNode }) {
  return <div className="readouts">{children}</div>;
}

/** A figure in its own sunken window: label, LED digits, and at most one small part beside them. */
export function Readout({
  label,
  value,
  tone,
  sub,
}: {
  label: string;
  value: string;
  tone?: "coral" | "sage" | "amber" | "plain";
  sub?: ReactNode;
}) {
  return (
    <div className="well">
      <span className="well-main">
        <span className="label">{label}</span>
        <span className={`value ${tone ?? ""}`}>
          <Odometer text={value} />
        </span>
      </span>
      {sub}
    </div>
  );
}

/** A change as an instrument gives it: which way, how much, and against what. */
export function Delta({
  change,
  percent,
  than,
  brief = false,
}: {
  change: number;
  percent?: number | null;
  than?: string;
  /** Only the share, when there is one. */
  brief?: boolean;
}) {
  const share = percent === null || percent === undefined || !Number.isFinite(percent) ? null : Math.round(Math.abs(percent));
  return (
    <span
      className={`delta ${change > 0 ? "up" : change < 0 ? "ok" : ""}`}
      role="text"
      aria-label={versus(change, than ?? "before", percent)}
    >
      <b>
        {change > 0 ? "▲" : change < 0 ? "▼" : "="} {brief && share !== null ? `${share}%` : money(Math.abs(change))}
      </b>
      {share === null || brief ? null : <b>{share}%</b>}
      {than ? <i>{than}</i> : null}
    </span>
  );
}

/** A selector's lamps: every position is marked and the one in use is lit. */
export function Lamps<T extends string>({
  label,
  options,
  value,
  tone = "",
}: {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  tone?: "coral" | "sage" | "amber" | "blue" | "";
}) {
  return (
    <span className={`lamps ${tone}`} role="img" aria-label={`${label}: ${options.find((item) => item.value === value)?.label ?? value}`}>
      {options.map((item) => (
        <span key={item.value} className={item.value === value ? "on" : ""}>
          <i />
          {item.label}
        </span>
      ))}
    </span>
  );
}

/** A row of small LEDs, one for each of something. */
export function Pips({ label, pips }: { label: string; pips: ("ok" | "up" | "warn" | "off")[] }) {
  return (
    <span
      className="pips"
      role="img"
      aria-label={label}
      style={{ "--columns": pips.length > 4 ? Math.ceil(pips.length / (pips.length > 10 ? 3 : 2)) : pips.length } as CSSProperties}
    >
      {pips.map((pip, index) => (
        <i key={index} className={pip} />
      ))}
    </span>
  );
}

const BAND = 15;

/** Low to high as a strip of dots with the expected place lit. */
export function Band({ low, at, high, format }: { low: number; at: number; high: number; format: (cents: number) => string }) {
  const place = high > low ? Math.round(((at - low) / (high - low)) * (BAND - 1)) : 0;
  return (
    <span className="band" role="img" aria-label={`Likely ${format(low)} to ${format(high)}`}>
      <span>{format(low)}</span>
      <span className="dots">
        {Array.from({ length: BAND }, (_, index) => (
          <i key={index} className={index === place ? "on" : ""} />
        ))}
      </span>
      <span>{format(high)}</span>
    </span>
  );
}

/**
 * A row of LED segments. Newly lit segments come on one by one, so a save that
 * moves spending visibly fills the meter instead of jumping.
 */
export function PaceMeter({
  value,
  capacity,
  pace,
  segments = 30,
  label,
  mark,
  cap,
  today,
}: {
  value: number;
  capacity: number;
  pace: number | null;
  segments?: number;
  label: string;
  /** Engraved at the pace. */
  mark?: string;
  /** Engraved over the far end. */
  cap?: string;
  /** Engraves the days of the week under the segments, with this one (0 is Monday) lit. */
  today?: number;
}) {
  const unit = capacity > 0 ? capacity / segments : 0;
  const lit = unit > 0 ? Math.min(segments, Math.max(0, Math.round(value / unit))) : 0;
  const paceIndex = unit > 0 && pace !== null ? Math.min(segments, pace / unit) : null;
  const previous = useRef(lit);
  const [from, setFrom] = useState(lit);
  useEffect(() => {
    setFrom(previous.current);
    previous.current = lit;
  }, [lit]);
  const description =
    pace === null
      ? `${label}`
      : `${label}. ${Math.round((value / Math.max(1, capacity)) * 100)}% used; pace marker at ${Math.round((pace / Math.max(1, capacity)) * 100)}%.`;
  return (
    <div className="meter">
      {cap ? (
        <div className="meter-cap" aria-hidden="true">
          {cap} <i>▼</i>
        </div>
      ) : null}
      <div
        className="segments"
        role="img"
        aria-label={description}
        style={{ "--count": segments } as CSSProperties}
      >
        {Array.from({ length: segments }, (_, index) => {
          const on = index < lit;
          const over = on && paceIndex !== null && index >= Math.ceil(paceIndex);
          const step = lit >= from ? index - from : from - index - 1;
          return (
            <span
              key={index}
              className={`segment ${on ? "lit" : ""} ${over ? "over" : ""}`}
              style={{ transitionDelay: `${Math.max(0, step) * 45}ms` }}
            />
          );
        })}
      </div>
      {today === undefined ? null : (
        <div className="meter-days" aria-hidden="true">
          {["M", "T", "W", "T", "F", "S", "S"].map((day, index) => (
            <span key={index} className={index === today ? "on" : index < today ? "past" : ""}>
              {day}
            </span>
          ))}
        </div>
      )}
      {paceIndex !== null && mark ? (
        <div className="pace-marker" aria-hidden="true">
          <span className={paceIndex > segments / 2 ? "before" : ""} style={{ left: `${(paceIndex / segments) * 100}%` }}>
            <i>▲</i>
            <span>{mark}</span>
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** Purchases drifting past a fixed label, repeated so there is never a gap. */
export function Ticker({ label, total, items }: { label: string; total: string; items: ReactNode[] }) {
  const reduced = useReducedMotion();
  if (!items.length) return null;
  const repeats = Math.max(1, Math.ceil(10 / items.length));
  const copy = (name: string, hidden: boolean) =>
    items.map((item, index) => (
      <span key={`${name}${index}`} aria-hidden={hidden || undefined}>
        {item}
      </span>
    ));
  return (
    <div className="ticker" role="group" aria-label={`${label}, ${total}`}>
      <span className="ticker-label" aria-hidden="true">
        {label} <b>{total}</b>
      </span>
      <div className="ticker-window">
        <div
          className="marquee"
          style={{ "--marquee-duration": `${Math.max(24, items.length * repeats * 4)}s` } as CSSProperties}
        >
          {copy("a", false)}
          {reduced ? null : Array.from({ length: repeats * 2 - 1 }, (_, index) => copy(`b${index}`, true))}
        </div>
      </div>
    </div>
  );
}

const FLAP_CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789$.,:-/+%";

function randomFlap(): string {
  return FLAP_CHARS[1 + Math.floor(Math.random() * (FLAP_CHARS.length - 1))] ?? "A";
}

/** A departures-board label: on change each cell flips through letters to the new text. */
export function SplitFlap({
  text,
  from,
  className = "",
}: {
  text: string;
  from?: string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const target = text.toUpperCase();
  const [cells, setCells] = useState<{ char: string; flips: number }[]>(() =>
    [...(from ?? text).toUpperCase().padEnd(target.length, " ")].map((char) => ({
      char,
      flips: 0,
    })),
  );
  const shown = useRef(cells);
  shown.current = cells;

  useEffect(() => {
    const current = shown.current.map((cell) => cell.char).join("");
    if (reduced || current === target) {
      setCells([...target].map((char) => ({ char, flips: 0 })));
      return;
    }
    const length = Math.max(current.length, target.length);
    const start = current.padEnd(length, " ");
    const goal = target.padEnd(length, " ");
    const queues = [...goal].map((char, index) =>
      char === start[index]
        ? []
        : [...Array.from({ length: 3 + (index % 4) }, randomFlap), char],
    );
    let tick = 0;
    let working = [...start].map((char) => ({ char, flips: 0 }));
    const timer = window.setInterval(() => {
      tick += 1;
      let busy = false;
      working = working.map((cell, index) => {
        const queue = queues[index] ?? [];
        if (tick < index * 1.5 || !queue.length) {
          busy ||= queue.length > 0;
          return cell;
        }
        busy = true;
        return { char: queue.shift() ?? cell.char, flips: cell.flips + 1 };
      });
      setCells(working);
      if (!busy) {
        window.clearInterval(timer);
        setCells([...target].map((char) => ({ char, flips: 0 })));
      }
    }, 55);
    return () => window.clearInterval(timer);
  }, [target, reduced]);

  return (
    <span className={`flap space ${className}`} role="text" aria-label={text}>
      {cells.map((cell, index) => (
        <span
          key={index}
          className={`flap-cell ${cell.char === " " ? "blank" : ""}`}
          aria-hidden="true"
        >
          <span key={cell.flips} className={cell.flips ? "flip" : ""}>
            {cell.char === " " ? " " : cell.char}
          </span>
        </span>
      ))}
    </span>
  );
}

export function Glyph({ category, small = false }: { category: string; small?: boolean }) {
  const color = categoryColor(category);
  return (
    <span className={`glyph-tile ${small ? "small" : ""}`} aria-hidden="true">
      <span className="glyph" style={{ filter: `drop-shadow(0 0 3px ${rgba(color, 0.85)})` }}>
        <i style={{ boxShadow: glyphShadow(category, hot(color, 0.15)) }} />
      </span>
    </span>
  );
}

export function Led({ color, lit, pulse = false }: { color: string; lit: boolean; pulse?: boolean }) {
  const style: CSSProperties = lit
    ? {
        background: `radial-gradient(circle at 35% 30%, #fff 0 12%, ${color} 45%, ${rgba(color, 0.55)} 100%)`,
        boxShadow: `0 0 10px ${rgba(color, 0.8)}, 0 0 22px ${rgba(color, 0.35)}, inset 0 -1px 2px rgba(0,0,0,.35)`,
      }
    : {
        background: `radial-gradient(circle at 35% 30%, rgba(255,255,255,.18) 0 10%, ${rgba(color, 0.22)} 45%, #0A0C08 100%)`,
        boxShadow: `inset 0 0 0 1px ${rgba(color, 0.45)}, 0 0 6px ${rgba(color, 0.18)}`,
      };
  return <span className={`led ${pulse ? "pulse" : ""}`} style={style} aria-hidden="true" />;
}
