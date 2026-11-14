import {
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import type { ForecastMonth } from "../api";
import {
  compactMoney,
  money,
  MONTH_SHORT,
  parseIso,
  plural,
  rangeLabel,
  versus,
  weekday,
  wholeMoney,
} from "../lib/format";
import { categoryColor, hot, rgba } from "../lib/glyphs";
import { Glyph } from "./instrument";

const ACCENT = "#D4F53C";
const AMBER = "#F2C14E";

/** The laid-out width of a chart's box, so it can draw at one unit per pixel. */
function useWidth(fallback: number): [(element: HTMLDivElement | null) => void, number] {
  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    if (!element) return;
    const measure = () => {
      if (element.clientWidth > 0) setWidth(element.clientWidth);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [setElement, width];
}

/**
 * Preview and pick for the columns of a chart. A mouse previews on hover and
 * picks on click; a finger previews on the first tap and picks on the second.
 * Arrow keys move between sibling columns; Enter or Space picks.
 */
export function usePreview() {
  const [active, setActive] = useState<string | null>(null);
  const armed = useRef(true);

  function bind(key: string, pick: (() => void) | null) {
    return {
      onPointerEnter: (event: PointerEvent<SVGGElement>) => {
        if (event.pointerType === "mouse") setActive(key);
      },
      onPointerDown: (event: PointerEvent<SVGGElement>) => {
        armed.current = event.pointerType === "mouse" || active === key;
      },
      onClick: () => {
        if (!armed.current) {
          armed.current = true;
          setActive(key);
          return;
        }
        pick?.();
      },
      onFocus: () => setActive(key),
      onBlur: () => setActive(null),
      onKeyDown: (event: KeyboardEvent<SVGGElement>) => {
        if (event.key === "Enter" || event.key === " ") {
          if (!pick) return;
          event.preventDefault();
          pick();
          return;
        }
        const column = event.currentTarget;
        const next =
          event.key === "ArrowLeft"
            ? column.previousElementSibling
            : event.key === "ArrowRight"
              ? column.nextElementSibling
              : null;
        if (next instanceof SVGGElement) {
          event.preventDefault();
          next.focus();
        }
      },
    };
  }

  function leave(event: PointerEvent<SVGSVGElement>) {
    if (event.pointerType === "mouse") setActive(null);
  }

  return { active, bind, leave };
}

/**
 * Background layers for a row of lit LED domes: a specular highlight up and to the
 * left, the lit body, and a shadow just below so each dot sits above its socket.
 */
function ledDots(color: string, body = 1.8): string {
  return [
    `radial-gradient(circle at 40% 36%, rgba(255,255,255,.9) 0, rgba(255,255,255,0) ${(body * 0.55).toFixed(2)}px)`,
    `radial-gradient(circle, ${hot(color, 0.5)} 0, ${color} ${body}px, ${rgba(color, 0.6)} ${(body + 1).toFixed(2)}px, transparent ${(body + 1.4).toFixed(2)}px)`,
    `radial-gradient(circle at 50% 64%, rgba(0,0,0,.75) ${(body + 0.6).toFixed(2)}px, transparent ${(body + 1.5).toFixed(2)}px)`,
  ].join(", ");
}

/** SVG defs for a domed LED dot in one color, tiled every 6 units. */
function DotPattern({ id, color, r = 2.2, shine = 0.75 }: { id: string; color: string; r?: number; shine?: number }) {
  return (
    <>
      <radialGradient id={`${id}g`} cx="38%" cy="34%" r="70%">
        <stop offset="0" stopColor={hot(color, shine)} />
        <stop offset="0.45" stopColor={color} />
        <stop offset="1" stopColor={rgba(color, 0.55)} />
      </radialGradient>
      <pattern id={id} width="6" height="6" patternUnits="userSpaceOnUse">
        <circle cx="3" cy="3.5" r={r} fill="rgba(0,0,0,.7)" />
        <circle cx="3" cy="3" r={r} fill={`url(#${id}g)`} />
      </pattern>
    </>
  );
}

/** Shared SVG defs: sunken sockets for unlit dots, a recessed well, glass sheen. */
function PanelDefs({ id, top, bottom }: { id: string; top: number; bottom: number }) {
  return (
    <>
      <pattern id={`${id}off`} width="6" height="6" patternUnits="userSpaceOnUse">
        <circle cx="3" cy="3.4" r="1.5" fill="#20261b" />
        <circle cx="3" cy="3" r="1.3" fill="#0b0d09" />
      </pattern>
      <linearGradient id={`${id}well`} x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stopColor="#030402" />
        <stop offset="1" stopColor="#0b0d09" />
      </linearGradient>
      <linearGradient id={`${id}sheen`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={top} y2={bottom}>
        <stop offset="0" stopColor="#fff" stopOpacity="0.06" />
        <stop offset="0.45" stopColor="#fff" stopOpacity="0" />
      </linearGradient>
    </>
  );
}

/** A recessed slot: dark well, shadowed top lip, lit bottom edge. */
function Well({ id, x, y, width, height }: { id: string; x: number; y: number; width: number; height: number }) {
  return (
    <g>
      <rect x={x - 3} y={y - 3} width={width + 6} height={height + 6} fill={`url(#${id}well)`} />
      <rect x={x - 3} y={y - 3} width={width + 6} height="2" fill="#000" opacity="0.7" />
      <rect x={x - 3} y={y + height + 2} width={width + 6} height="1" fill="#fff" opacity="0.06" />
      <rect x={x} y={y} width={width} height={height} fill={`url(#${id}off)`} />
    </g>
  );
}

interface Day {
  date: string;
  spent: number;
  count: number;
  future: boolean;
}

/** A Monday-first month where each day's dot size and glow show what was spent. */
export function DotCalendar({
  days,
  today,
  onPick,
  dailyAllowance,
}: {
  days: Day[];
  today: string | null;
  onPick?: (date: string) => void;
  dailyAllowance?: number | null;
}) {
  const [hover, setHover] = useState<Day | null>(null);
  if (!days.length) return null;
  const first = parseIso(days[0]?.date ?? "2000-01-01");
  const blanks = (first.getDay() + 6) % 7;
  const largest = Math.max(1, ...days.map((day) => day.spent));
  const biggest = days.reduce<Day | null>(
    (best, day) => (!day.future && day.spent > (best?.spent ?? 0) ? day : best),
    null,
  );
  const quiet = days.filter((day) => !day.future && day.count === 0).length;

  function describe(day: Day): string {
    const date = parseIso(day.date);
    const label = `${weekday(day.date)} ${MONTH_SHORT[date.getMonth()]} ${date.getDate()}`;
    if (day.future) {
      return dailyAllowance
        ? `${label} · ahead · ${money(dailyAllowance)}/day keeps you on plan`
        : `${label} · ahead`;
    }
    if (!day.count) return `${label} · no spending ✓`;
    return `${label} · ${money(day.spent)} · ${plural(day.count, "purchase")}${day.date === today ? " · today" : ""}`;
  }

  const summary = hover
    ? describe(hover)
    : [
        biggest ? `Biggest day · ${weekday(biggest.date)} ${parseIso(biggest.date).getDate()} · ${money(biggest.spent)}` : "No spending yet",
        plural(quiet, "no-spend day"),
        "point at a day",
      ].join("  ·  ");

  return (
    <div className="stack">
      <div className="cal-head" aria-hidden="true">
        {["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"].map((name) => (
          <span key={name}>{name}</span>
        ))}
      </div>
      <div className="cal" onMouseLeave={() => setHover(null)}>
        {Array.from({ length: blanks }, (_, index) => (
          <span key={`blank${index}`} aria-hidden="true" />
        ))}
        {days.map((day) => {
          const share = day.spent > 0 ? Math.sqrt(day.spent / largest) : 0;
          const radius = 0.9 + 2.6 * share;
          const lit: CSSProperties | undefined =
            day.spent > 0
              ? {
                  backgroundImage: `radial-gradient(circle at 44% 40%, rgba(255,255,255,.85) 0, rgba(255,255,255,0) ${(radius * 0.4).toFixed(2)}px), radial-gradient(circle, ${hot(ACCENT, 0.55)} 0, ${ACCENT} ${(radius * 0.55).toFixed(2)}px, ${rgba(ACCENT, 0.7)} ${radius.toFixed(2)}px, transparent ${(radius + 0.6).toFixed(2)}px)`,
                  filter: `drop-shadow(0 0 ${(2 + 3 * share).toFixed(1)}px ${rgba(ACCENT, 0.75)})`,
                }
              : undefined;
          const background =
            day.spent > 0
              ? `radial-gradient(90% 90% at 50% 60%, ${rgba(ACCENT, 0.03 + 0.1 * share)}, transparent 70%), #060705`
              : undefined;
          return (
            <button
              key={day.date}
              type="button"
              className={`cell ${day.date === today ? "today" : ""} ${day.future ? "future" : ""}`}
              style={background ? { background } : undefined}
              aria-label={describe(day)}
              onMouseEnter={() => setHover(day)}
              onFocus={() => setHover(day)}
              onBlur={() => setHover(null)}
              onClick={() => onPick?.(day.date)}
            >
              <span className="day">{parseIso(day.date).getDate()}</span>
              <span className="matrix" aria-hidden="true" />
              {lit ? <span className="lit" style={lit} aria-hidden="true" /> : null}
            </button>
          );
        })}
      </div>
      <div className="readout-bar" role="status">
        <span className="caret" aria-hidden="true">
          ▸
        </span>
        <span>{summary}</span>
      </div>
    </div>
  );
}

function dotValue(largest: number, dots: number): number {
  const steps = [100, 200, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000, 250000, 500000];
  return steps.find((step) => largest / step <= dots) ?? Math.ceil(largest / dots);
}

export function CategoryMeters({
  categories,
  onPick,
}: {
  categories: { category: string; spent: number }[];
  onPick?: (category: string) => void;
}) {
  const positive = categories.filter((item) => item.spent > 0);
  if (!positive.length) return null;
  const largest = Math.max(...positive.map((item) => item.spent));
  const unit = dotValue(largest, 34);
  return (
    <div className="stack tight">
      <span className="small dim">
        one lit dot = {money(unit)}
      </span>
      {positive.map((item) => {
        const color = categoryColor(item.category);
        const count = Math.max(1, Math.round(item.spent / unit));
        return (
          <button
            key={item.category}
            type="button"
            className="meter-row"
            style={{ cursor: onPick ? "pointer" : "default" }}
            onClick={() => onPick?.(item.category)}
            aria-label={`${item.category}: ${money(item.spent)}`}
          >
            <Glyph category={item.category} />
            <span className="small">{item.category}</span>
            <span className="track" aria-hidden="true">
              <span className="dots" />
              <span
                className="fill"
                style={{
                  width: `${count * 9}px`,
                  backgroundImage: ledDots(color),
                  filter: `drop-shadow(0 0 3px ${rgba(color, 0.8)})`,
                }}
              />
            </span>
            <span className="num small" style={{ textAlign: "right" }}>
              {money(item.spent)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function monthShort(month: string): string {
  const [year, number] = month.split("-").map(Number);
  return `${MONTH_SHORT[(number ?? 1) - 1]?.toUpperCase()}${number === 1 ? ` ${String(year).slice(2)}` : ""}`;
}

/** Narrowest column whose month and value labels still clear their neighbors'. */
const MIN_COLUMN = 38;

/** One column of a `DotColumns` chart: a month or a week. */
export interface Column {
  key: string;
  /** The label under the column. */
  name: string;
  /** A second label under it (the year, or a week's month), shown when it changes. */
  group: string;
  /** How the readout names the column. */
  title: string;
  spent: number;
}

interface TrendColumn extends Column {
  average: number | null;
  forecast: ForecastMonth | null;
  /** A month that has not started yet: forecast only. */
  ahead: boolean;
}

function monthColumn(month: string, spent: number): Column {
  const [year, number] = month.split("-").map(Number);
  const name = MONTH_SHORT[(number ?? 1) - 1]?.toUpperCase() ?? month;
  return { key: month, name, group: String(year), title: `${name} ${year}`, spent };
}

/** Months as chart columns, labeled JAN with the year under the first of each year. */
export function monthColumns(items: { month: string; spent: number }[]): Column[] {
  return items.map((item) => monthColumn(item.month, item.spent));
}

/** Weeks as chart columns, labeled by the Monday's date with the month under the first of each month. */
export function weekColumns(items: { week: string; end: string; label: string; spent: number }[]): Column[] {
  return items.map((item) => {
    const monday = parseIso(item.week);
    return {
      key: item.week,
      name: String(monday.getDate()),
      group: MONTH_SHORT[monday.getMonth()]?.toUpperCase() ?? "",
      title: `${item.label} · ${rangeLabel(item.week, item.end)}`.toUpperCase(),
      spent: item.spent,
    };
  });
}

/** What the readout under the chart says about one column. */
function describeColumn(
  item: TrendColumn,
  averageLabel: string | null,
): { text: string; tone?: "up" | "ok" | "warn" }[] {
  const title = { text: item.title };
  const plan = item.forecast;
  if (plan) {
    return [
      title,
      ...(item.ahead ? [] : [{ text: `${money(item.spent)} so far` }]),
      { text: `${item.ahead ? "forecast" : "heading for"} ~${wholeMoney(plan.expected)}`, tone: "warn" },
      { text: `likely ${wholeMoney(plan.low)}–${wholeMoney(plan.high)}` },
    ];
  }
  if (!averageLabel || item.average === null) return [title, { text: money(item.spent) }];
  const gap = item.spent - item.average;
  return [
    title,
    { text: money(item.spent) },
    { text: versus(gap, `the ${averageLabel}`), tone: gap > 0 ? "up" : "ok" },
  ];
}

/**
 * Totals per month or week as columns of lit dots with a dotted rolling-average line and,
 * when given, a forecast: amber dots up to the likely low, fainter ones up to the
 * likely high and a bar at the expected amount. Drawn at one unit per pixel, so
 * labels keep their size and only as many months as fit are shown. Pointing at a
 * column describes it in the readout below; picking one calls `onPick`.
 */
export function DotColumns({
  data,
  highlight,
  average,
  averageLabel = "3-month average",
  unit = "month",
  forecast,
  onPick,
  pickable,
}: {
  data: Column[];
  /** What one column is, for the readout's prompt: "month" or "week". */
  unit?: string;
  highlight?: string;
  average?: number[];
  averageLabel?: string;
  forecast?: ForecastMonth[];
  onPick?: (month: string) => void;
  /** Months `onPick` accepts; all of them when omitted. */
  pickable?: string[];
}) {
  const id = useId().replace(/:/g, "");
  const [box, width] = useWidth(720);
  const { active, bind, leave } = usePreview();
  const [lineOn, setLineOn] = useState(true);
  const [planOn, setPlanOn] = useState(true);
  if (!data.length) return null;

  const plan = planOn ? (forecast ?? []) : [];
  const known = new Set(data.map((item) => item.key));
  const columns: TrendColumn[] = [
    ...data.map((item, index) => ({
      ...item,
      average: average?.[index] ?? null,
      forecast: plan.find((entry) => entry.month === item.key) ?? null,
      ahead: false,
    })),
    ...plan
      .filter((entry) => !known.has(entry.month))
      .map((entry) => ({
        ...monthColumn(entry.month, entry.spent),
        average: null,
        forecast: entry,
        ahead: !entry.partial,
      })),
  ];

  // As many of the latest months as fit, moved back if the open month is older.
  const fit = Math.max(3, Math.floor(width / MIN_COLUMN));
  const latest = Math.max(0, columns.length - fit);
  const picked = columns.findIndex((item) => item.key === highlight);
  const from = picked >= 0 ? Math.min(Math.max(0, picked - 1), latest) : latest;
  const shown = columns.slice(from, from + fit);

  const height = 244;
  const top = 38;
  const base = 194;
  const column = width / shown.length;
  // Bars are a whole number of dots wide. Each column draws from its own origin,
  // so the dot grid starts at its left edge and the columns stay evenly spaced.
  const barWidth = Math.max(12, Math.floor(Math.min(54, column * 0.62) / 6) * 6);
  const left = (index: number) => Math.round((index + 0.5) * column - barWidth / 2);
  const center = (index: number) => left(index) + barWidth / 2;
  const largest = Math.max(
    1,
    ...shown.map((item) => Math.max(item.spent, item.average ?? 0, item.forecast?.high ?? 0)),
  );
  const rise = (value: number) => Math.round(((base - top) * Math.max(0, value)) / largest / 6) * 6;
  /** Dot heights of a column: spent, then the likely and possible parts of a forecast. */
  const stack = (item: TrendColumn) => {
    const spent = item.ahead ? 0 : rise(item.spent);
    const low = item.forecast ? Math.max(spent, rise(item.forecast.low)) : spent;
    const high = item.forecast ? Math.max(low, rise(item.forecast.high)) : spent;
    const expected = item.forecast ? Math.min(high, Math.max(low, rise(item.forecast.expected))) : spent;
    return { spent, low, high, expected };
  };
  const everyValue = column >= 60;
  const averagePoints = lineOn
    ? shown
        .map((item, index) => (item.average === null ? null : `${center(index)},${base - rise(item.average)}`))
        .filter(Boolean)
        .join(" ")
    : "";
  const aheadAt = shown.findIndex((item) => item.ahead);
  const canPick = (item: TrendColumn) =>
    Boolean(onPick) && !item.ahead && (!pickable || pickable.includes(item.key));

  const focused = shown.find((item) => item.key === active) ?? null;
  const resting = shown.find((item) => item.key === highlight) ?? shown[shown.length - 1];
  const described = focused ?? resting;
  const stop = described?.key;
  const hint = !focused
    ? `point at a ${unit}`
    : canPick(focused) && focused.key !== highlight
      ? "click to open it"
      : null;

  return (
    <div className="stack tight" ref={box}>
      <svg
        className="chart"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={`Net spending by ${unit}`}
        onPointerLeave={leave}
      >
        <defs>
          <PanelDefs id={id} top={top} bottom={base} />
          <DotPattern id={`${id}on`} color={ACCENT} />
          <DotPattern id={`${id}dim`} color="#5f731f" shine={0.3} />
          <DotPattern id={`${id}plan`} color={AMBER} shine={0.4} />
          <linearGradient id={`${id}fade`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={base + 4} y2={base + 18}>
            <stop offset="0" stopColor="#fff" stopOpacity="0.32" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
          <mask id={`${id}mirror`} maskUnits="userSpaceOnUse" x="0" y={base} width={width} height="24">
            <rect x="0" y={base + 4} width={width} height="14" fill={`url(#${id}fade)`} />
          </mask>
        </defs>
        <g>
          {shown.map((item, index) => {
            const origin = left(index);
            const x = 0;
            const h = stack(item);
            const on = item.key === highlight;
            const lit = item.key === active;
            const fill = `url(#${id}${on || lit ? "on" : "dim"})`;
            const pick = canPick(item);
            return (
              <g
                key={item.key}
                className={`column ${pick ? "pick" : ""}`}
                role={pick ? "button" : "img"}
                tabIndex={item.key === stop ? 0 : -1}
                aria-label={`${describeColumn(item, lineOn ? averageLabel : null)
                  .map((part) => part.text)
                  .join(", ")}${on ? ", open" : ""}`}
                transform={`translate(${origin} 0)`}
                {...bind(item.key, pick ? () => onPick?.(item.key) : null)}
              >
                <rect x={index * column - origin} y="0" width={column} height={height} fill="transparent" />
                <Well id={id} x={x} y={top} width={barWidth} height={base - top} />
                {lit ? (
                  <rect
                    x={x - 3.5}
                    y={top - 3.5}
                    width={barWidth + 7}
                    height={base - top + 7}
                    fill="none"
                    stroke="#E9ECE3"
                    strokeOpacity="0.4"
                  />
                ) : null}
                {h.spent ? (
                  <>
                    <rect
                      x={x}
                      y={base - h.spent}
                      width={barWidth}
                      height={h.spent}
                      fill={fill}
                      style={on || lit ? { filter: `drop-shadow(0 0 4px ${rgba(ACCENT, on ? 0.7 : 0.4)})` } : undefined}
                    />
                    <rect
                      x={x}
                      y={base + 4}
                      width={barWidth}
                      height={14}
                      fill={fill}
                      mask={`url(#${id}mirror)`}
                      aria-hidden="true"
                    />
                  </>
                ) : null}
                {item.forecast ? (
                  <>
                    <rect
                      x={x}
                      y={base - h.low}
                      width={barWidth}
                      height={h.low - h.spent}
                      fill={`url(#${id}plan)`}
                      opacity="0.75"
                    />
                    <rect
                      x={x}
                      y={base - h.high}
                      width={barWidth}
                      height={h.high - h.low}
                      fill={`url(#${id}plan)`}
                      opacity="0.28"
                    />
                    <rect
                      x={x - 3}
                      y={base - h.expected - 1}
                      width={barWidth + 6}
                      height="2"
                      fill={AMBER}
                      style={{ filter: `drop-shadow(0 0 3px ${rgba(AMBER, 0.8)})` }}
                    />
                  </>
                ) : null}
                <text
                  x={x + barWidth / 2}
                  y={base + 30}
                  textAnchor="middle"
                  style={on ? { fill: ACCENT } : lit ? { fill: "#E9ECE3" } : undefined}
                >
                  {item.name}
                </text>
                {item.group !== shown[index - 1]?.group ? (
                  <text x={x + barWidth / 2} y={base + 43} textAnchor="middle" style={{ fontSize: 10 }}>
                    {item.group}
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
        <g pointerEvents="none">
          <rect x="0" y={top - 3} width={width} height={base - top + 6} fill={`url(#${id}sheen)`} />
          {aheadAt > 0 ? (
            <>
              <line
                x1={aheadAt * column}
                x2={aheadAt * column}
                y1="6"
                y2={base + 3}
                stroke="#3a4234"
                strokeDasharray="2 4"
              />
              <text x={aheadAt * column + 8} y="16" style={{ fill: AMBER, fontSize: 10, letterSpacing: 1 }}>
                FORECAST
              </text>
            </>
          ) : null}
          {averagePoints ? (
            <polyline
              points={averagePoints}
              fill="none"
              stroke={AMBER}
              strokeWidth="2"
              strokeDasharray="1 6"
              strokeLinecap="round"
            />
          ) : null}
          {/* Values go on last with a dark edge: above the column and the average
              line, or right on a forecast's expected bar. */}
          {shown.map((item, index) => {
            const on = item.key === highlight;
            const lit = item.key === active;
            if (!everyValue && !on && !lit) return null;
            const h = stack(item);
            const line = lineOn && item.average !== null ? rise(item.average) : 0;
            return (
              <text
                key={item.key}
                className="value"
                x={center(index)}
                y={base - (item.forecast ? h.expected : Math.max(h.spent, line)) - 8}
                textAnchor="middle"
                style={{ fill: item.forecast ? AMBER : on ? ACCENT : lit ? "#E9ECE3" : "#A7AF9E" }}
              >
                {item.forecast ? `~${compactMoney(item.forecast.expected)}` : compactMoney(item.spent)}
              </text>
            );
          })}
        </g>
      </svg>
      {described ? (
        <div className="readout-bar wrap" aria-hidden="true">
          <span className="caret">▸</span>
          {describeColumn(described, lineOn ? averageLabel : null).map((part) => (
            <span key={part.text} className={part.tone}>
              {part.text}
            </span>
          ))}
          {hint ? <span className="faint">{hint}</span> : null}
        </div>
      ) : null}
      <div className="legend">
        <span>
          <i style={{ backgroundColor: ACCENT, boxShadow: `0 0 6px ${ACCENT}` }} />
          Net spent
        </span>
        {average ? (
          <button type="button" aria-pressed={lineOn} onClick={() => setLineOn((value) => !value)}>
            <i style={{ backgroundColor: AMBER }} />
            {averageLabel}
          </button>
        ) : null}
        {forecast?.length ? (
          <button type="button" aria-pressed={planOn} onClick={() => setPlanOn((value) => !value)}>
            <i style={{ backgroundColor: "#8d7430" }} />
            Forecast
          </button>
        ) : null}
      </div>
    </div>
  );
}

/** Money in (up, sage) and out (down, coral) per month with the net as amber LEDs. */
export function CashFlowChart({
  data,
}: {
  data: { month: string; income: number; expenses: number; refunds: number; net: number }[];
}) {
  const id = useId().replace(/:/g, "");
  if (!data.length) return null;
  const width = 720;
  const height = 260;
  const middle = 120;
  const reach = 96;
  const shown = data.slice(-12);
  const largest = Math.max(
    1,
    ...shown.map((item) => Math.max(item.income + item.refunds, item.expenses, Math.abs(item.net))),
  );
  const column = width / shown.length;
  const barWidth = Math.min(46, column * 0.56);
  const scale = (value: number) => Math.round((reach * value) / largest / 6) * 6;
  return (
    <div className="stack tight">
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Monthly cash flow">
        <defs>
          <PanelDefs id={id} top={middle - reach} bottom={middle + reach} />
          <DotPattern id={`${id}in`} color="#9FD39B" />
          <DotPattern id={`${id}out`} color="#FF8A70" />
          <radialGradient id={`${id}net`} cx="38%" cy="34%" r="70%">
            <stop offset="0" stopColor="#fff6dc" />
            <stop offset="0.45" stopColor="#F2C14E" />
            <stop offset="1" stopColor="#b5861f" />
          </radialGradient>
        </defs>
        {shown.map((item, index) => {
          const x = Math.round((index + 0.5) * column - barWidth / 2);
          const up = scale(item.income + item.refunds);
          const down = scale(item.expenses);
          const net = middle - Math.round((reach * item.net) / largest);
          return (
            <g key={item.month}>
              <Well id={id} x={x} y={middle - reach} width={barWidth} height={reach * 2} />
              <rect x={x} y={middle - up} width={barWidth} height={up} fill={`url(#${id}in)`} />
              <rect x={x} y={middle} width={barWidth} height={down} fill={`url(#${id}out)`} />
              <circle
                cx={x + barWidth / 2}
                cy={net}
                r="4.5"
                fill={`url(#${id}net)`}
                style={{ filter: "drop-shadow(0 0 4px rgba(242,193,78,.8))" }}
              >
                <title>{`${item.month}: net ${money(item.net, { signed: true })}`}</title>
              </circle>
              <text x={x + barWidth / 2} y={height - 8} textAnchor="middle">
                {monthShort(item.month)}
              </text>
            </g>
          );
        })}
        <line x1="0" x2={width} y1={middle} y2={middle} stroke="#3a4234" strokeDasharray="2 4" />
        <rect
          x="0"
          y={middle - reach - 3}
          width={width}
          height={reach * 2 + 6}
          fill={`url(#${id}sheen)`}
          pointerEvents="none"
        />
      </svg>
      <div className="legend">
        <span>
          <i style={{ backgroundColor: "#9FD39B" }} />
          Income + refunds
        </span>
        <span>
          <i style={{ backgroundColor: "#FF8A70" }} />
          Expenses
        </span>
        <span>
          <i style={{ backgroundColor: "#F2C14E" }} />
          Net
        </span>
      </div>
    </div>
  );
}

/** Category changes as bars left (less) and right (more) of a center line. */
export function DriverBars({
  drivers,
  onPick,
}: {
  drivers: { category: string; current: number; previous: number; change: number; percent: number | null }[];
  onPick?: (category: string) => void;
}) {
  const largest = Math.max(1, ...drivers.map((item) => Math.abs(item.change)));
  return (
    <div className="stack tight">
      {drivers.map((item) => {
        const share = (Math.abs(item.change) / largest) * 50;
        const color = item.change > 0 ? "#FF8A70" : "#9FD39B";
        return (
          <button
            key={item.category}
            type="button"
            className={`meter-row ${onPick ? "pick" : ""}`}
            style={{ gridTemplateColumns: "26px minmax(90px,150px) minmax(0,1fr) 150px" }}
            onClick={() => onPick?.(item.category)}
            title={onPick ? `See ${item.category} transactions` : undefined}
          >
            <Glyph category={item.category} small />
            <span className="small">{item.category}</span>
            <span className="track" aria-hidden="true">
              <span
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: "50%",
                  width: 1,
                  background: "#2F352B",
                  zIndex: 1,
                }}
              />
              <span
                style={{
                  position: "absolute",
                  top: 2,
                  bottom: 2,
                  left: item.change > 0 ? "50%" : `${50 - share}%`,
                  width: `${share}%`,
                  backgroundImage: ledDots(color, 1.9),
                  backgroundSize: "7px 10px",
                  filter: `drop-shadow(0 0 3px ${rgba(color, 0.7)})`,
                }}
              />
            </span>
            <span className="num small" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
              <span className={item.change > 0 ? "up" : "ok"}>{money(item.change, { signed: true })}</span>
              <br />
              <span className="dim tiny">
                {money(item.previous)} → {money(item.current)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
