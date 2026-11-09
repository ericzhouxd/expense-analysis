import {
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

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

/** The glass-covered LED panel: the glare follows the pointer and it tilts slightly. */
export function Housing({
  children,
  label,
  className = "",
  scanlines = true,
  tilt = true,
}: {
  children: ReactNode;
  label: string;
  className?: string;
  scanlines?: boolean;
  tilt?: boolean;
}) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);

  function move(event: MouseEvent<HTMLDivElement>) {
    const element = ref.current;
    if (!element) return;
    const box = element.getBoundingClientRect();
    const x = (event.clientX - box.left) / box.width;
    const y = (event.clientY - box.top) / box.height;
    element.style.setProperty("--gx", `${(x * 100).toFixed(1)}%`);
    element.style.setProperty("--gy", `${(y * 100).toFixed(1)}%`);
    if (tilt && !reduced) {
      element.style.setProperty("--rx", `${((0.5 - y) * 2.4).toFixed(2)}deg`);
      element.style.setProperty("--ry", `${((x - 0.5) * 3.2).toFixed(2)}deg`);
    }
  }

  function leave() {
    for (const name of ["--gx", "--gy", "--rx", "--ry"]) ref.current?.style.removeProperty(name);
  }

  return (
    <div ref={ref} className={`housing ${className}`} onMouseMove={move} onMouseLeave={leave}>
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
  tone?: "accent" | "over";
}) {
  return (
    <div className={`hero boot ${tone === "over" ? "over" : ""}`}>
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

export function Readout({
  label,
  value,
  tone,
  sub,
}: {
  label: string;
  value: string;
  tone?: "coral" | "sage" | "text";
  sub?: string;
}) {
  return (
    <div className="well">
      <span className="label">{label}</span>
      <span className={`value ${tone ?? ""}`}>
        {tone === "text" ? value : <Odometer text={value} />}
      </span>
      {sub ? <span className="sub">{sub}</span> : null}
    </div>
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
  paceLabel,
}: {
  value: number;
  capacity: number;
  pace: number | null;
  segments?: number;
  label: string;
  paceLabel?: string;
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
    <div className="stack tight">
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
      {paceIndex !== null && paceLabel ? (
        <div className="pace-marker" aria-hidden="true">
          <span style={{ left: `${(paceIndex / segments) * 100}%` }}>▲ {paceLabel}</span>
        </div>
      ) : null}
    </div>
  );
}

export function Ticker({ label, items }: { label: string; items: ReactNode[] }) {
  const reduced = useReducedMotion();
  if (!items.length) return null;
  const duration = Math.max(18, items.length * 5);
  return (
    <div className="ticker" aria-label={label}>
      <div
        className="marquee"
        style={{ "--marquee-duration": `${duration}s` } as CSSProperties}
      >
        {items.map((item, index) => (
          <span key={`a${index}`}>{item}</span>
        ))}
        {reduced
          ? null
          : items.map((item, index) => (
              <span key={`b${index}`} aria-hidden="true">
                {item}
              </span>
            ))}
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

export function Card({
  title,
  hint,
  actions,
  children,
  className = "",
  id,
}: {
  title: string;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`card ${className}`} aria-label={title} id={id}>
      <div className="card-head">
        <h2>
          <span className="led-dot" aria-hidden="true" />
          {title}
        </h2>
        {hint ? <span className="hint">{hint}</span> : null}
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Collapsible({
  title,
  hint,
  children,
  open,
  id,
}: {
  title: string;
  hint?: ReactNode;
  children: ReactNode;
  open?: boolean;
  id?: string;
}) {
  return (
    <details className="card" open={open} id={id}>
      <summary>
        <div className="card-head">
          <h2>
            <span className="led-dot" aria-hidden="true" />
            {title}
          </h2>
          {hint ? <span className="hint">{hint}</span> : null}
        </div>
      </summary>
      <div className="stack">{children}</div>
    </details>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** ◀ LABEL ▶ with a split-flap label: used to step through months and quarters. */
export function Stepper({
  label,
  onPrevious,
  onNext,
  canPrevious,
  canNext,
  name,
  from,
}: {
  label: string;
  onPrevious: () => void;
  onNext: () => void;
  canPrevious: boolean;
  canNext: boolean;
  name: string;
  from?: string;
}) {
  return (
    <div className="stepper" role="group" aria-label={name}>
      <button type="button" onClick={onPrevious} disabled={!canPrevious} aria-label={`Previous ${name}`}>
        ◀
      </button>
      <SplitFlap text={label} from={from} />
      <button type="button" onClick={onNext} disabled={!canNext} aria-label={`Next ${name}`}>
        ▶
      </button>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      {children}
    </div>
  );
}
